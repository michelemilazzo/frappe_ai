import frappe


def after_install():
    create_ai_settings()


def create_ai_settings():
    if frappe.db.exists("DocType", "AI Settings"):
        return

    frappe.get_doc({
        "doctype": "DocType",
        "name": "AI Settings",
        "module": "Frappe AI",
        "issingle": 1,
        "fields": [
            {
                "fieldname": "provider",
                "fieldtype": "Select",
                "label": "Provider",
                "options": "OpenRouter\nOpenAI\nOpenCode.ai",
                "default": "OpenRouter",
            },
            {
                "fieldname": "api_key",
                "fieldtype": "Password",
                "label": "API Key",
            },
            {
                "fieldname": "model",
                "fieldtype": "Data",
                "label": "Model",
                "default": "openai/gpt-4o-mini",
            },
            {
                "fieldname": "system_prompt",
                "fieldtype": "Long Text",
                "label": "System Prompt",
                "default": "You are a helpful assistant for Frappe/ERPNext. Help users with their questions about the system.",
            },
        ],
    }).insert(ignore_permissions=True)
    frappe.db.commit()
