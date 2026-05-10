import frappe
import json
import os
import re
import ast
from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
    "type": "object",
    "function": {
        "name": "analyze_code",
        "description": "Analyze Frappe app code for patterns, bugs, performance issues, and best practices violations. Returns a structured report with findings, severity levels, and suggested fixes. Use this when asked to review, debug, or improve app code.",
        "parameters": {
            "type": "object",
            "properties": {
                "doctype": {
                    "type": "string",
                    "description": "DocType name to analyze (analyzes its Python controller and JS files)",
                },
                "app_name": {
                    "type": "string",
                    "description": "App name to analyze (analyzes all Python files)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Specific file path relative to the app (e.g. 'doctype/sales_invoice/sales_invoice.py')",
                },
                "analysis_type": {
                    "type": "string",
                    "description": "Type of analysis: 'security', 'performance', 'best_practices', 'bugs', 'full'",
                    "enum": ["security", "performance", "best_practices", "bugs", "full"],
                    "default": "full",
                },
                "depth": {
                    "type": "string",
                    "description": "Analysis depth: 'quick' or 'deep'",
                    "enum": ["quick", "deep"],
                    "default": "quick",
                },
            },
            "required": [],
        },
    },
}

ANTIPATTERNS = {
    "sql_injection": {
        "pattern": r'frappe\.db\.sql\(["\'][^"\']*%s[^"\']*["\']\s*%',
        "severity": "critical",
        "message": "Potential SQL injection. Use parameterized queries.",
        "fix": "Use frappe.db.sql('SELECT ... WHERE field=%s', (value,)) with tuple params",
    },
    "no_permission_check": {
        "pattern": r'frappe\.db\.set_value\([^)]*ignore_permissions\s*=\s*True[^)]*\)',
        "severity": "warning",
        "message": "Bypassing permission checks in set_value.",
        "fix": "Ensure this is intentional and properly guarded.",
    },
    "missing_doc_perms": {
        "pattern": r'\.insert\(\s*ignore_permissions\s*=\s*(True|1)\s*\)',
        "severity": "warning",
        "message": "Insert with ignore_permissions=True.",
        "fix": "Use ignore_permissions=True only in seed/data migration scripts.",
    },
    "hardcoded_password": {
        "pattern": r'password\s*=\s*["\'][^"\']+["\']',
        "severity": "critical",
        "message": "Hardcoded password detected.",
        "fix": "Use frappe.utils.password or environment variables.",
    },
    "select_star": {
        "pattern": r"frappe\.db\.sql.*SELECT\s+\*\s+FROM",
        "severity": "warning",
        "message": "SELECT * is inefficient. Specify only needed columns.",
        "fix": "List specific field names in your query.",
    },
    "n1_query": {
        "pattern": r'for\s+\w+\s+in\s+.*:\s*\n\s*frappe\.db\.(sql|get_all|get_list)\(',
        "severity": "high",
        "message": "Possible N+1 query pattern inside a loop.",
        "fix": "Batch the queries or use frappe.get_all with filters.",
    },
}


def execute(args: dict, user: str) -> dict:
    """Analyze code for issues."""
    analysis_type = args.get("analysis_type", "full")
    depth = args.get("depth", "quick")

    files_to_analyze = []

    if args.get("doctype"):
        files_to_analyze = find_doctype_files(args["doctype"])
    elif args.get("app_name"):
        files_to_analyze = find_app_files(args["app_name"])
    elif args.get("file_path"):
        files_to_analyze = [args["file_path"]]
    else:
        return {"error": "Specify doctype, app_name, or file_path"}

    findings = []
    for filepath in files_to_analyze:
        try:
            content = read_file(filepath)
            if not content:
                continue

            file_findings = []
            if analysis_type in ("security", "full", "bugs"):
                file_findings.extend(check_antipatterns(filepath, content))
            if analysis_type in ("performance", "full"):
                file_findings.extend(check_performance(filepath, content))
            if analysis_type in ("best_practices", "full"):
                file_findings.extend(check_best_practices(filepath, content))
            if depth == "deep" and analysis_type in ("full", "bugs", "performance"):
                file_findings.extend(deep_analysis(filepath, content))

            if file_findings:
                findings.append({"file": filepath, "issues": file_findings})
        except Exception as e:
            findings.append({"file": filepath, "error": str(e)})

    critical = sum(1 for f in findings for i in f.get("issues", [])
                    if i.get("severity") == "critical")
    high = sum(1 for f in findings for i in f.get("issues", [])
               if i.get("severity") == "high")
    warning = sum(1 for f in findings for i in f.get("issues", [])
                  if i.get("severity") == "warning")
    low = sum(1 for f in findings for i in f.get("issues", [])
              if i.get("severity") == "low")

    return {
        "findings": findings,
        "summary": {
            "total_issues": critical + high + warning + low,
            "critical": critical,
            "high": high,
            "warning": warning,
            "low": low,
            "files_analyzed": len(files_to_analyze),
        },
    }


def find_doctype_files(doctype: str) -> list:
    """Find all files related to a DocType."""
    files = []
    for app in frappe.get_installed_apps():
        base = get_app_path(app)
        if not base:
            continue
        dt_slug = doctype.replace(" ", "_").lower()
        py_file = os.path.join(base, "doctype", dt_slug, f"{dt_slug}.py")
        if os.path.exists(py_file):
            files.append(py_file)
        js_file = os.path.join(base, "doctype", dt_slug, f"{dt_slug}.js")
        if os.path.exists(js_file):
            files.append(js_file)
    return files


def find_app_files(app_name: str) -> list:
    """Find all Python files in an app."""
    base = get_app_path(app_name)
    if not base:
        return []
    py_files = []
    for root, dirs, files in os.walk(base):
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))
    return sorted(py_files)


def get_app_path(app_name: str) -> str:
    """Get filesystem path of an app."""
    for base in ["/home/frappe/frappe-bench/apps", "/opt/frappe-bench/apps"]:
        path = os.path.join(base, app_name)
        if os.path.exists(path):
            return path
    return ""


def read_file(filepath: str) -> str:
    """Read file content safely."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def check_antipatterns(filepath: str, content: str) -> list:
    """Check for code anti-patterns and security issues."""
    issues = []
    lines = content.split("\n")
    for name, check in ANTIPATTERNS.items():
        for i, line in enumerate(lines, 1):
            if re.search(check["pattern"], line, re.IGNORECASE):
                issues.append({
                    "type": name,
                    "severity": check["severity"],
                    "line": i,
                    "line_content": line.strip()[:100],
                    "message": check["message"],
                    "suggested_fix": check["fix"],
                })
    return issues


def check_performance(filepath: str, content: str) -> list:
    """Check for performance issues."""
    issues = []
    lines = content.split("\n")

    for i, line in enumerate(lines, 1):
        if "frappe.db.get_all(" in line or "frappe.get_list(" in line:
            if "limit" not in line.lower():
                issues.append({
                    "type": "unbounded_query",
                    "severity": "warning",
                    "line": i,
                    "line_content": line.strip()[:80],
                    "message": "Query without limit could be slow on large tables.",
                    "suggested_fix": "Add a 'limit' parameter.",
                })

    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                complexity = count_complexity(node)
                if complexity > 15:
                    issues.append({
                        "type": "high_complexity",
                        "severity": "warning",
                        "line": node.lineno,
                        "message": f"Function '{node.name}' has cyclomatic complexity {complexity}.",
                        "suggested_fix": "Refactor into smaller functions.",
                    })
    except SyntaxError:
        pass

    return issues


def check_best_practices(filepath: str, content: str) -> list:
    """Check for best practices violations."""
    issues = []
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("def ") and i + 1 < len(lines):
            next_line = lines[i].strip()
            if not (next_line.startswith('"""') or next_line.startswith("'''")
                    or next_line.startswith('#')):
                issues.append({
                    "type": "missing_docstring",
                    "severity": "low",
                    "line": i,
                    "message": "Function without docstring.",
                    "suggested_fix": "Add a docstring.",
                })
    return issues


def deep_analysis(filepath: str, content: str) -> list:
    """Deep analysis: complexity, code smells, dead code."""
    issues = []
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    if handler.type is None:
                        issues.append({
                            "type": "bare_except",
                            "severity": "warning",
                            "line": handler.lineno,
                            "message": "Bare except clause catches all exceptions.",
                            "suggested_fix": "Catch specific exceptions.",
                        })
            if isinstance(node, ast.FunctionDef):
                if hasattr(node, 'end_lineno') and node.end_lineno:
                    length = node.end_lineno - node.lineno
                    if length > 100:
                        issues.append({
                            "type": "long_function",
                            "severity": "low",
                            "line": node.lineno,
                            "message": f"Function '{node.name}' is {length} lines long.",
                            "suggested_fix": "Split into smaller functions.",
                        })
    except SyntaxError:
        pass
    return issues


def count_complexity(node: ast.FunctionDef) -> int:
    """Calculate cyclomatic complexity."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += len(child.values) - 1
        elif isinstance(child, ast.Try):
            complexity += len(child.handlers)
    return complexity


register_tool("analyze_code", SCHEMA, execute)