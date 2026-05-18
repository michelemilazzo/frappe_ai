import frappe


def after_install():
    _create_ai_settings_doctype()


def _create_ai_settings_doctype():
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
                "options": "Claude (Anthropic)\nOpenRouter\nOpenCode.ai\nOpenAI",
                "default": "Claude (Anthropic)",
                "reqd": 1,
            },
            {
                "fieldname": "api_key",
                "fieldtype": "Password",
                "label": "API Key",
                "reqd": 1,
            },
            {
                "fieldname": "model",
                "fieldtype": "Data",
                "label": "Model",
                "default": "claude-sonnet-4-6",
                "description": "Claude: claude-sonnet-4-6, claude-haiku-4-5 | OpenRouter: openai/gpt-4o-mini | OpenAI: gpt-4o",
            },
            {
                "fieldname": "system_prompt",
                "fieldtype": "Long Text",
                "label": "System Prompt",
                "default": "You are a helpful assistant integrated into Frappe/ERPNext. Help users navigate the system, write queries, understand documents, and solve problems. Be concise and practical.",
            },
        ],
    }).insert(ignore_permissions=True)
