import frappe
from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
    "type": "object",
    "function": {
        "name": "manage_app",
        "description": "Manage Frappe apps: check status, install, uninstall, or update. For safety, install/uninstall/update require shell access and return the command to run.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["status", "install", "uninstall", "update"],
                },
                "app_name": {
                    "type": "string",
                    "description": "Name of the app (e.g. 'erpnext', 'hrms', 'ecommerce')",
                },
            },
            "required": ["action", "app_name"],
        },
    },
}


def execute(args: dict, user: str) -> dict:
    """Manage Frappe apps (check status only for safety)."""
    action = args.get("action", "status")
    app_name = args.get("app_name", "")

    if action in ("install", "uninstall", "update"):
        return {
            "error": f"Action '{action}' requires admin shell access.",
            "action_required": f"bench --site {frappe.local.site} {action}-app {app_name}",
            "status": "shell_command_required",
        }

    if action == "status":
        installed = frappe.get_installed_apps()
        return {
            "app_name": app_name,
            "installed": app_name in installed,
            "all_apps": installed,
        }

    return {"error": f"Unknown action: {action}"}


register_tool("manage_app", SCHEMA, execute)