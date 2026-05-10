import frappe
from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
    "type": "object",
    "function": {
        "name": "learn_app",
        "description": "Learn the structure and behavior of a Frappe app or DocType. Returns a comprehensive summary of modules, DocTypes, business logic, and permissions.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Name of the app to learn (e.g. 'erpnext', 'hrms')",
                },
                "doctype": {
                    "type": "string",
                    "description": "Specific DocType to analyze in depth",
                },
                "depth": {
                    "type": "string",
                    "description": "Analysis depth: 'overview' or 'deep'",
                    "enum": ["overview", "deep"],
                    "default": "overview",
                },
            },
            "required": ["app_name"],
        },
    },
}


def execute(args: dict, user: str) -> dict:
    """Learn how an app or DocType works."""
    app_name = args.get("app_name", "")
    doctype = args.get("doctype", "")
    depth = args.get("depth", "overview")

    if not app_name:
        return {"error": "Specify 'app_name'"}

    result = {
        "app_name": app_name,
        "modules": [],
        "key_doctypes": [],
        "triggers": [],
    }

    modules = frappe.get_all("Module Def", filters={"app_name": app_name})
    result["modules"] = [m["module_name"] for m in modules]

    module_names = [m["module_name"] for m in modules]
    doctypes = frappe.get_all(
        "DocType",
        filters={"module": ["in", module_names], "istable": 0, "custom": 0},
        fields=["name", "module", "issingle", "creation"],
        limit=20,
    )
    result["key_doctypes"] = [d["name"] for d in doctypes]

    if doctype:
        result["doctype_detail"] = analyze_doctype(doctype)

    if depth == "deep":
        scripts = frappe.get_all(
            "Server Script",
            filters={"docstatus": ["!=", 2]},
            fields=["name", "dt", "script_type", "enabled"],
        )
        result["server_scripts"] = scripts

    return result


def analyze_doctype(doctype_name: str) -> dict:
    """Deep analysis of a single DocType."""
    dt = frappe.get_doc("DocType", doctype_name)
    return {
        "name": dt.name,
        "module": dt.module,
        "fields": [
            {
                "name": f.fieldname,
                "type": f.fieldtype,
                "label": f.label,
                "reqd": f.reqd,
                "read_only": f.read_only,
                "options": f.options,
            }
            for f in dt.fields
            if f.fieldtype not in ("Section Break", "Column Break", "Tab Break")
        ],
        "permissions": [
            {
                "role": p.role,
                "read": p.read,
                "write": p.write,
                "create": p.create,
                "delete": p.delete,
                "submit": p.submit,
            }
            for p in dt.permissions
        ],
        "has_web_view": dt.has_web_view,
        "is_submittable": dt.is_submittable,
        "track_changes": dt.track_changes,
        "autoname": dt.autoname,
    }


register_tool("learn_app", SCHEMA, execute)