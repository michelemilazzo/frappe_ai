import frappe
import requests
from frappe import _


@frappe.whitelist()
def send_message(message: str, history: list | None = None):
    """Send a message to the AI and return the response."""
    settings = _get_settings()

    if not settings.get("api_key"):
        frappe.throw(_("AI API Key not configured. Go to AI Settings to configure."))

    messages = _build_messages(settings.get("system_prompt", ""), history or [], message)

    response = _call_provider(
        provider=settings.get("provider", "OpenRouter"),
        api_key=settings["api_key"],
        model=settings.get("model", "openai/gpt-4o-mini"),
        messages=messages,
    )

    return {"reply": response}


def _get_settings():
    if not frappe.db.exists("DocType", "AI Settings"):
        return {}
    doc = frappe.get_single("AI Settings")
    return {
        "provider": doc.provider,
        "api_key": doc.get_password("api_key") if doc.api_key else None,
        "model": doc.model,
        "system_prompt": doc.system_prompt,
    }


def _build_messages(system_prompt, history, user_message):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for entry in history:
        messages.append({"role": entry.get("role", "user"), "content": entry.get("content", "")})
    messages.append({"role": "user", "content": user_message})
    return messages


def _call_provider(provider, api_key, model, messages):
    if provider == "OpenCode.ai":
        url = "https://api.opencode.ai/v1/chat/completions"
    else:
        url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": frappe.utils.get_url(),
        "X-Title": "Frappe AI",
    }

    resp = requests.post(url, json={"model": model, "messages": messages}, headers=headers, timeout=60)

    if not resp.ok:
        frappe.throw(_("AI provider error: {0}").format(resp.text[:200]))

    return resp.json()["choices"][0]["message"]["content"]
