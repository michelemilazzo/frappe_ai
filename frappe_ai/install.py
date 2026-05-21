import frappe

OLLAMA_BASE_URL = "http://10.10.0.4:11434"
OLLAMA_DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant integrated into Frappe/ERPNext. "
    "Help users navigate the system, write queries, understand documents, "
    "and solve problems. Be concise and practical."
)


def after_install():
    _create_ai_settings_doctype()
    _set_default_settings()


def _create_ai_settings_doctype():
    if frappe.db.exists("DocType", "AI Settings"):
        # Add Ollama option to existing provider select if not present
        meta = frappe.get_meta("AI Settings")
        provider_field = next((f for f in meta.fields if f.fieldname == "provider"), None)
        if provider_field and "Ollama (Local)" not in (provider_field.options or ""):
            frappe.db.set_value(
                "DocField",
                {"parent": "AI Settings", "fieldname": "provider"},
                "options",
                "Ollama (Local)\nClaude (Anthropic)\nOpenRouter\nOpenCode.ai\nOpenAI",
            )
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
                "options": "Ollama (Local)\nClaude (Anthropic)\nOpenRouter\nOpenCode.ai\nOpenAI",
                "default": "Ollama (Local)",
                "reqd": 1,
            },
            {
                "fieldname": "api_key",
                "fieldtype": "Password",
                "label": "API Key",
                "description": "Not required for Ollama (Local)",
            },
            {
                "fieldname": "model",
                "fieldtype": "Data",
                "label": "Model",
                "default": OLLAMA_DEFAULT_MODEL,
                "description": (
                    "Ollama: qwen2.5:7b | "
                    "Claude: claude-sonnet-4-6 | "
                    "OpenRouter: openai/gpt-4o-mini | "
                    "OpenAI: gpt-4o"
                ),
            },
            {
                "fieldname": "ollama_base_url",
                "fieldtype": "Data",
                "label": "Ollama Base URL",
                "default": OLLAMA_BASE_URL,
                "description": "Internal URL of the Ollama server (ai-mmos-core)",
                "read_only": 1,
            },
            {
                "fieldname": "system_prompt",
                "fieldtype": "Long Text",
                "label": "System Prompt",
                "default": DEFAULT_SYSTEM_PROMPT,
            },
        ],
    }).insert(ignore_permissions=True)


def _set_default_settings():
    """Auto-configure AI Settings to use local Ollama — no user action required."""
    if not frappe.db.exists("DocType", "AI Settings"):
        return
    doc = frappe.get_single("AI Settings")
    if not doc.provider or doc.provider == "Claude (Anthropic)":
        doc.provider = "Ollama (Local)"
        doc.model = OLLAMA_DEFAULT_MODEL
        if not doc.system_prompt:
            doc.system_prompt = DEFAULT_SYSTEM_PROMPT
        doc.save(ignore_permissions=True)
