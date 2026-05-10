import frappe
from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
    "type": "object",
    "function": {
        "name": "suggest_improvements",
        "description": "Analyze the Frappe site and suggest improvements: unused features, optimization opportunities, best practice gaps, and automation possibilities.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category: 'performance', 'security', 'ux', 'automation', 'all'",
                    "enum": ["performance", "security", "ux", "automation", "all"],
                    "default": "all",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of suggestions (default: 10)",
                    "default": 10,
                },
            },
            "required": [],
        },
    },
}


def execute(args: dict, user: str) -> dict:
    """Generate improvement suggestions for the site."""
    category = args.get("category", "all")
    max_results = args.get("max_results", 10)

    suggestions = []
    if category in ("performance", "all"):
        suggestions.extend(get_performance_suggestions())
    if category in ("security", "all"):
        suggestions.extend(get_security_suggestions())
    if category in ("ux", "all"):
        suggestions.extend(get_ux_suggestions())
    if category in ("automation", "all"):
        suggestions.extend(get_automation_suggestions())

    suggestions.sort(key=lambda s: s.get("impact_score", 0), reverse=True)

    return {
        "suggestions": suggestions[:max_results],
        "total": len(suggestions),
        "category": category,
    }


def get_performance_suggestions() -> list:
    suggestions = []
    try:
        slow_tables = frappe.db.sql("""
            SELECT table_name, table_rows
            FROM information_schema.tables
            WHERE table_schema = %s AND table_rows > 10000
            ORDER BY table_rows DESC LIMIT 10
        """, frappe.conf.db_name, as_dict=True)
        if slow_tables:
            suggestions.append({
                "type": "performance",
                "title": "Large tables detected",
                "description": f"{len(slow_tables)} tables have >10K rows.",
                "impact_score": 8,
                "action": "Review and add database indexes for frequently queried columns.",
                "priority": "high",
            })
    except Exception:
        pass

    try:
        pending = frappe.db.count("RQ Job", {"status": "queued"})
        if pending > 50:
            suggestions.append({
                "type": "performance",
                "title": f"{pending} pending background jobs",
                "description": "Background job queue is backed up.",
                "impact_score": 7,
                "action": "Check: Desk → Background Jobs",
                "priority": "high",
            })
    except Exception:
        pass

    return suggestions


def get_security_suggestions() -> list:
    suggestions = []
    try:
        system_settings = frappe.get_single("System Settings")
        if not system_settings.enable_password_policy:
            suggestions.append({
                "type": "security",
                "title": "Password policy not enabled",
                "description": "Strong password policy is not enforced.",
                "impact_score": 9,
                "action": "Settings → System Settings → Password Policy",
                "priority": "critical",
            })
    except Exception:
        pass
    return suggestions


def get_ux_suggestions() -> list:
    suggestions = []
    workspaces = frappe.get_all("Workspace", filters={"is_standard": 0})
    if not workspaces:
        suggestions.append({
            "type": "ux",
            "title": "No custom workspaces",
            "description": "Workspaces organize your Desk navigation.",
            "impact_score": 5,
            "action": "Create: Desk → Workspace → New",
            "priority": "medium",
        })
    return suggestions


def get_automation_suggestions() -> list:
    suggestions = []
    notifications = frappe.get_all("Notification", filters={"enabled": 1})
    if not notifications:
        suggestions.append({
            "type": "automation",
            "title": "No automated notifications",
            "description": "Set up notifications for key events.",
            "impact_score": 6,
            "action": "Desk → Automation → Notification",
            "priority": "medium",
        })

    server_scripts = frappe.get_all("Server Script", filters={"enabled": 1})
    if not server_scripts:
        suggestions.append({
            "type": "automation",
            "title": "No server scripts active",
            "description": "Server scripts enable custom business logic.",
            "impact_score": 5,
            "action": "Desk → Automation → Server Script",
            "priority": "low",
        })

    return suggestions


register_tool("suggest_improvements", SCHEMA, execute)