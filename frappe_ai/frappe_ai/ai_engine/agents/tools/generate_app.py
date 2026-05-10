import frappe
import os
from datetime import datetime
from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
    "type": "object",
    "function": {
        "name": "generate_app",
        "description": "Generate scaffolding for a new Frappe app, including DocType definitions, Python controllers, and basic UI.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "Name of the new app (lowercase, snake_case)",
                    "pattern": "^[a-z][a-z0-9_]+$",
                },
                "description": {
                    "type": "string",
                    "description": "Brief description of the app's purpose",
                },
                "doctypes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "DocType name (title case)"},
                            "fields": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "fieldname": {"type": "string"},
                                        "label": {"type": "string"},
                                        "fieldtype": {
                                            "type": "string",
                                            "enum": ["Data", "Int", "Float", "Currency",
                                                     "Date", "Select", "Link", "Table",
                                                     "Text", "Check", "Attach", "Password"],
                                        },
                                        "options": {"type": "string"},
                                        "reqd": {"type": "boolean", "default": False},
                                    },
                                    "required": ["fieldname", "label", "fieldtype"],
                                },
                            },
                            "permissions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "role": {"type": "string"},
                                        "read": {"type": "int", "default": 1},
                                        "write": {"type": "int", "default": 0},
                                        "create": {"type": "int", "default": 0},
                                        "delete": {"type": "int", "default": 0},
                                    },
                                },
                            },
                        },
                    },
                    "description": "List of DocTypes to generate",
                },
                "generate_views": {
                    "type": "boolean",
                    "description": "Generate List, Form, and Report views (default: true)",
                    "default": True,
                },
            },
            "required": ["app_name", "doctypes"],
        },
    },
}


def execute(args: dict, user: str) -> dict:
    """Generate app scaffolding."""
    app_name = args.get("app_name", "")
    doctypes = args.get("doctypes", [])
    description = args.get("description", f"Custom app: {app_name}")

    if not app_name or not doctypes:
        return {
            "error": "Provide 'app_name' and at least one DocType in 'doctypes'",
            "example": {
                "app_name": "my_app",
                "doctypes": [{
                    "name": "My DocType",
                    "fields": [
                        {"fieldname": "title", "label": "Title", "fieldtype": "Data", "reqd": 1}
                    ],
                }],
            },
        }

    if not app_name.islower() or " " in app_name:
        return {"error": "app_name must be lowercase with underscores (e.g. 'my_app')"}

    scaffold = generate_scaffold(app_name, description, doctypes, args.get("generate_views", True))

    return {
        "status": "generated",
        "app_name": app_name,
        "structure": scaffold["structure"],
        "files": scaffold["files"],
        "next_steps": [
            f"Create app folder: mkdir -p apps/{app_name}",
            "Copy generated files into the folder structure",
            f"bench --site {frappe.local.site} install-app {app_name}",
            "Test and iterate",
        ],
    }


def generate_scaffold(app_name: str, description: str, doctypes: list, generate_views: bool) -> dict:
    """Generate the full app scaffold."""
    files = {}
    app_label = app_name.replace("_", " ").title()

    files["__init__.py"] = ""

    hooks_content = f'''app_name = "{app_name}"
app_title = "{app_label}"
app_publisher = "{frappe.session.user}"
app_description = "{description}"
app_email = "user@example.com"
app_license = "mit"
app_version = "0.1.0"
'''
    files["hooks.py"] = hooks_content

    setup_content = f'''import frappe

def after_install():
    frappe.logger().info("{app_label} installed successfully.")
'''
    files["setup.py"] = setup_content

    for dt in doctypes:
        dt_name = dt["name"]
        dt_filename = dt_name.lower().replace(" ", "_")

        doctype_json = {
            "doctype": "DocType",
            "name": dt_name,
            "module": app_label,
            "owner": "Administrator",
            "fields": dt["fields"],
            "permissions": dt.get("permissions", [
                {"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}
            ]),
        }
        files[f"doctype/{dt_filename}/{dt_filename}.json"] = json.dumps(doctype_json, indent=2)

        py_content = f'''import frappe
from frappe.model.document import Document


class {dt_name.replace(" ", "")}(Document):
    def validate(self):
        pass

    def before_save(self):
        pass

    def on_trash(self):
        pass
'''
        files[f"doctype/{dt_filename}/{dt_filename}.py"] = py_content

        js_content = f"""frappe.ui.form.on("{dt_name}", {{
    refresh(frm) {{
        // Custom logic here
    }},
}});
"""
        files[f"doctype/{dt_filename}/{dt_filename}.js"] = js_content

    readme = f"""# {app_label}

{description}

## Installation

```bash
bench get-app {app_name}
bench --site <site-name> install-app {app_name}
```
"""
    files["README.md"] = readme

    structure = [f"📁 {app_name}/"]
    for path in sorted(files.keys()):
        indent = "  " * path.count("/")
        structure.append(f"{indent}📄 {os.path.basename(path)}")

    return {"structure": structure, "files": files}


register_tool("generate_app", SCHEMA, execute)