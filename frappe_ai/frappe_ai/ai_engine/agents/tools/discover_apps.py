import frappe
from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
    "type": "object",
    "function": {
        "name": "discover_apps",
        "description": "Discover all Frappe apps installed on the current site, including their DocTypes, pages, reports, and modules. Use this to understand the full application landscape before answering questions or making changes.",
        "parameters": {
            "type": "object",
            "properties": {
                "include_modules": {
                    "type": "boolean",
                    "description": "Include module list for each app (default: true)",
                    "default": True,
                },
                "include_doctypes": {
                    "type": "boolean",
                    "description": "Include DocType list for each app (default: true)",
                    "default": True,
                },
                "include_reports": {
                    "type": "boolean",
                    "description": "Include report list for each app (default: true)",
                    "default": True,
                },
                "include_pages": {
                    "type": "boolean",
                    "description": "Include custom pages for each app (default: true)",
                    "default": True,
                },
                "include_domains": {
                    "type": "boolean",
                    "description": "Include domain assignments (default: true)",
                    "default": True,
                },
            },
            "required": [],
        },
    },
}


def execute(args: dict, user: str) -> dict:
    """Discover all installed apps and their components."""
    result = {"apps": [], "summary": {}}

    apps = frappe.get_installed_apps()
    result["summary"]["total_apps"] = len(apps)

    for app_name in sorted(apps):
        app_info = {
            "name": app_name,
            "version": get_app_version(app_name),
            "modules": [],
            "doctypes": [],
            "reports": [],
            "pages": [],
            "domains": [],
        }

        if args.get("include_modules", True):
            modules = frappe.get_all(
                "Module Def",
                filters={"app_name": app_name},
                fields=["module_name", "label", "icon"],
                order_by="idx",
            )
            app_info["modules"] = modules

        if args.get("include_doctypes", True):
            doctypes = frappe.get_all(
                "DocType",
                filters={
                    "owner": app_name,
                    "istable": 0,
                    "custom": 0,
                },
                fields=[
                    "name", "module", "issingle",
                    "istable", "read_only", "creation",
                ],
                order_by="name",
            )
            app_info["doctypes"] = doctypes

            custom_doctypes = frappe.get_all(
                "DocType",
                filters={
                    "owner": app_name,
                    "istable": 0,
                    "custom": 1,
                },
                fields=["name", "module"],
                order_by="name",
            )
            app_info["custom_doctypes"] = custom_doctypes

        if args.get("include_reports", True):
            module_names = [m["module_name"] for m in app_info["modules"]]
            if module_names:
                reports = frappe.get_all(
                    "Report",
                    filters={"module": ["in", module_names]},
                    fields=["name", "module", "ref_doctype", "report_type"],
                    order_by="name",
                )
                app_info["reports"] = reports

        if args.get("include_pages", True):
            module_names = [m["module_name"] for m in app_info["modules"]]
            if module_names:
                pages = frappe.get_all(
                    "Page",
                    filters={"module": ["in", module_names]},
                    fields=["name", "title", "module"],
                )
                app_info["pages"] = pages

        if args.get("include_domains", True):
            domains = frappe.get_all(
                "Has Domain",
                filters={"parent": app_name},
                fields=["domain"],
            )
            app_info["domains"] = [d["domain"] for d in domains]

        result["apps"].append(app_info)

    all_doctypes = sum(len(a.get("doctypes", [])) for a in result["apps"])
    all_reports = sum(len(a.get("reports", [])) for a in result["apps"])
    result["summary"]["total_doctypes"] = all_doctypes
    result["summary"]["total_reports"] = all_reports
    result["summary"]["apps_list"] = [a["name"] for a in result["apps"]]

    return result


def get_app_version(app_name: str) -> str:
    """Get version string for a given app."""
    try:
        from importlib.metadata import version
        return version(app_name) or "unknown"
    except Exception:
        try:
            return frappe.get_attr(f"{app_name}.__version__") or "unknown"
        except Exception:
            return "unknown"


register_tool("discover_apps", SCHEMA, execute)