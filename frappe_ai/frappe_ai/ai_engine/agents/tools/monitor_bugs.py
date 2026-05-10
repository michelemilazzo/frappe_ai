import frappe
import json
from datetime import datetime, timedelta
from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
    "type": "object",
    "function": {
        "name": "monitor_bugs",
        "description": "Monitor error logs, identify bugs, suggest fixes. Use actions: get_errors, analyze_patterns, suggest_fixes, auto_fix.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["get_errors", "analyze_patterns", "suggest_fixes", "auto_fix"],
                },
                "hours": {
                    "type": "integer",
                    "description": "Look back hours (default: 24)",
                    "default": 24,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max errors to return (default: 50)",
                    "default": 50,
                },
                "doctype": {
                    "type": "string",
                    "description": "Filter by DocType",
                },
            },
            "required": ["action"],
        },
    },
}


def execute(args: dict, user: str) -> dict:
    """Monitor and analyze bugs."""
    action = args.get("action", "get_errors")
    hours = args.get("hours", 24)
    limit = args.get("limit", 50)
    since = datetime.now() - timedelta(hours=hours)

    if action == "get_errors":
        return get_recent_errors(since, limit, args.get("doctype"))
    elif action == "analyze_patterns":
        return analyze_error_patterns(since, limit)
    elif action == "suggest_fixes":
        return suggest_fixes(since, limit)
    elif action == "auto_fix":
        return auto_fix(since, limit, args.get("doctype"))

    return {"error": f"Unknown action: {action}"}


def get_recent_errors(since: datetime, limit: int, doctype_filter: str = None) -> dict:
    """Retrieve recent error logs."""
    try:
        filters = {"creation": [">=", since.strftime("%Y-%m-%d %H:%M:%S")]}
        if doctype_filter:
            filters["method"] = ["like", f"%{doctype_filter}%"]

        errors = frappe.get_all(
            "Error Log",
            filters=filters,
            fields=["name", "error", "method", "creation", "user"],
            limit=limit,
            order_by="creation desc",
        )

        return {
            "total_errors": len(errors),
            "errors": [
                {
                    "id": e.name,
                    "error_message": (e.error or "")[:500],
                    "method": e.method,
                    "timestamp": e.creation,
                    "user": e.user,
                }
                for e in errors
            ],
        }
    except Exception as ex:
        return {"error": str(ex)}


def analyze_error_patterns(since: datetime, limit: int) -> dict:
    """Analyze error patterns and group by type."""
    errors_data = get_recent_errors(since, limit)
    if "error" in errors_data:
        return errors_data

    patterns = {}
    for err in errors_data.get("errors", []):
        error_type = categorize_error(err["error_message"])
        if error_type not in patterns:
            patterns[error_type] = {"count": 0, "examples": [], "methods": set()}
        patterns[error_type]["count"] += 1
        patterns[error_type]["methods"].add(err.get("method", "unknown"))
        if len(patterns[error_type]["examples"]) < 3:
            patterns[error_type]["examples"].append(err["error_message"][:200])

    for k in patterns:
        patterns[k]["methods"] = list(patterns[k]["methods"])

    most_common = max(patterns.items(), key=lambda x: x[1]["count"]) if patterns else None

    return {
        "patterns": patterns,
        "period": f"last {since.strftime('%Y-%m-%d %H:%M')}",
        "most_common": most_common,
    }


def suggest_fixes(since: datetime, limit: int) -> dict:
    """Suggest fixes for common errors."""
    patterns = analyze_error_patterns(since, limit)
    if "error" in patterns:
        return patterns

    suggestions = []
    for error_type, data in patterns.get("patterns", {}).items():
        fix = get_fix_for_error_type(error_type, data)
        if fix:
            suggestions.append({
                "error_type": error_type,
                "occurrences": data["count"],
                "suggestion": fix["suggestion"],
                "severity": fix["severity"],
                "auto_fixable": fix.get("auto_fixable", False),
            })

    return {
        "suggestions": sorted(suggestions, key=lambda x: x["occurrences"], reverse=True),
        "total_issues": len(suggestions),
    }


def auto_fix(since: datetime, limit: int, doctype_filter: str = None) -> dict:
    """Attempt automatic fixes for known issues."""
    suggestions = suggest_fixes(since, limit)
    if "error" in suggestions:
        return suggestions

    fixes_applied = []
    fixes_failed = []

    for s in suggestions.get("suggestions", []):
        if s.get("auto_fixable"):
            try:
                fixes_applied.append({
                    "error_type": s["error_type"],
                    "status": "would_apply",
                    "action": s.get("auto_fix_action"),
                })
            except Exception as e:
                fixes_failed.append({
                    "error_type": s["error_type"],
                    "error": str(e),
                })

    return {
        "fixes_applied": fixes_applied,
        "fixes_failed": fixes_failed,
        "manual_fixes": [s for s in suggestions.get("suggestions", []) if not s.get("auto_fixable")],
    }


KNOWN_ERROR_PATTERNS = {
    "permission_error": {
        "keywords": ["permission", "not permitted", "access denied", "insufficient"],
        "severity": "high",
        "suggestion": "Check user roles and DocType permissions.",
        "auto_fixable": False,
    },
    "doctype_not_found": {
        "keywords": ["does not exist", "doctype not found", "no doctype"],
        "severity": "critical",
        "suggestion": "The referenced DocType may have been renamed or deleted.",
        "auto_fixable": False,
    },
    "link_validation": {
        "keywords": ["link validation", "invalid link", "does not exist"],
        "severity": "high",
        "suggestion": "A document references a non-existent record.",
        "auto_fixable": False,
    },
    "syntax_error": {
        "keywords": ["syntax error", "invalid syntax", "indentation"],
        "severity": "critical",
        "suggestion": "Python syntax error in the code.",
        "auto_fixable": False,
    },
    "missing_field": {
        "keywords": ["mandatory", "required field", "missing value"],
        "severity": "medium",
        "suggestion": "A required field is missing.",
        "auto_fixable": False,
    },
    "duplicate_entry": {
        "keywords": ["duplicate entry", "duplicate", "unique constraint"],
        "severity": "medium",
        "suggestion": "Duplicate record detected.",
        "auto_fixable": False,
    },
    "import_error": {
        "keywords": ["import error", "module not found", "no module"],
        "severity": "high",
        "suggestion": "Missing Python module.",
        "auto_fixable": False,
    },
    "database_error": {
        "keywords": ["database error", "column", "table", "sql error"],
        "severity": "high",
        "suggestion": "Database schema issue. May need to run: bench migrate",
        "auto_fixable": False,
    },
    "timeout": {
        "keywords": ["timeout", "timed out", "deadline"],
        "severity": "medium",
        "suggestion": "Request timed out. Check server resources.",
        "auto_fixable": False,
    },
    "memory_error": {
        "keywords": ["memory", "out of memory", "OOM"],
        "severity": "high",
        "suggestion": "Server running out of memory.",
        "auto_fixable": False,
    },
}


def categorize_error(error_message: str) -> str:
    """Categorize an error message into a known type."""
    error_lower = error_message.lower()
    for error_type, config in KNOWN_ERROR_PATTERNS.items():
        for keyword in config["keywords"]:
            if keyword.lower() in error_lower:
                return error_type
    return "unknown"


def get_fix_for_error_type(error_type: str, data: dict) -> dict:
    """Get fix suggestion for a specific error type."""
    config = KNOWN_ERROR_PATTERNS.get(error_type, {
        "severity": "low",
        "suggestion": "Manual investigation needed.",
        "auto_fixable": False,
    })
    return {
        **config,
        "affected_methods": list(data.get("methods", []))[:5],
    }


register_tool("monitor_bugs", SCHEMA, execute)