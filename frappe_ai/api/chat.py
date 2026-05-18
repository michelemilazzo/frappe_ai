import json
import frappe
import requests
from frappe import _


@frappe.whitelist()
def send_message(message: str, history=None):
    """Send a message to the configured AI provider and return the response."""
    if isinstance(history, str):
        try:
            history = json.loads(history)
        except (json.JSONDecodeError, TypeError):
            history = []

    settings = _get_settings()

    if not settings.get("api_key"):
        frappe.throw(_("AI API Key not configured. Go to AI Settings to configure."))

    messages = _build_messages(settings.get("system_prompt", ""), history or [], message)

    reply = _call_provider(
        provider=settings.get("provider", "Claude (Anthropic)"),
        api_key=settings["api_key"],
        model=settings.get("model", "claude-sonnet-4-6"),
        messages=messages,
    )

    return {"reply": reply}


def _get_settings():
    if not frappe.db.exists("DocType", "AI Settings"):
        return {}
    doc = frappe.get_single("AI Settings")
    return {
        "provider": doc.provider,
        "api_key": doc.get_password("api_key") if doc.api_key else None,
        "model": doc.model or "claude-sonnet-4-6",
        "system_prompt": doc.system_prompt,
    }


def _build_messages(system_prompt, history, user_message):
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    for entry in (history or []):
        role = entry.get("role", "user")
        content = entry.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages


def _call_provider(provider, api_key, model, messages):
    if provider == "Claude (Anthropic)":
        return _call_anthropic(api_key, model, messages)
    elif provider == "OpenAI":
        return _call_openai_compatible("https://api.openai.com/v1/chat/completions", api_key, model, messages)
    else:
        # OpenRouter (default)
        return _call_openai_compatible("https://openrouter.ai/api/v1/chat/completions", api_key, model, messages)


def _call_anthropic(api_key, model, messages):
    # Anthropic uses a different format: system is separate, no system in messages list
    system_content = ""
    filtered = []
    for m in messages:
        if m["role"] == "system":
            system_content = m["content"]
        else:
            filtered.append(m)

    payload = {
        "model": model,
        "max_tokens": 1024,
        "messages": filtered,
    }
    if system_content:
        payload["system"] = system_content

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        json=payload,
        headers=headers,
        timeout=60,
    )

    if not resp.ok:
        frappe.throw(_("Anthropic API error: {0}").format(resp.text[:300]))

    return resp.json()["content"][0]["text"]


def _call_openai_compatible(url, api_key, model, messages):
    site_url = frappe.utils.get_url()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": site_url,
        "X-Title": "Frappe AI",
    }

    resp = requests.post(
        url,
        json={"model": model, "messages": messages, "max_tokens": 1024},
        headers=headers,
        timeout=60,
    )

    if not resp.ok:
        frappe.throw(_("AI provider error {0} {1}: {2}").format(resp.status_code, url, resp.text[:300]))

    try:
        data = resp.json()
    except Exception:
        frappe.throw(_("AI provider returned invalid response (status {0}): {1}").format(resp.status_code, resp.text[:300]))

    return data["choices"][0]["message"]["content"]
