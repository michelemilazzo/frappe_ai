import json
import re
import subprocess
import frappe
import requests
from frappe import _

# Matches http/https URLs
_URL_RE = re.compile(r'https?://[^\s\)\]>"\',]+', re.IGNORECASE)


@frappe.whitelist()
def send_message(message: str, history=None):
    """Send a message to the configured AI provider and return the response."""
    if isinstance(history, str):
        try:
            history = json.loads(history)
        except (json.JSONDecodeError, TypeError):
            history = []

    settings = _get_settings()
    provider = settings.get("provider", "Claude (Anthropic)")

    if provider not in ("Claude Code (locale)", "Claude Code (local)") and not settings.get("api_key"):
        frappe.throw(_("AI API Key not configured. Go to AI Settings to configure."))

    message = _inject_url_content(message)
    messages = _build_messages(settings.get("system_prompt", ""), history or [], message)

    reply = _call_provider(
        provider=provider,
        api_key=settings.get("api_key"),
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


def _inject_url_content(message: str) -> str:
    """Find URLs in message, fetch their text content and append as context."""
    urls = list(dict.fromkeys(_URL_RE.findall(message)))  # deduplicated, order preserved
    if not urls:
        return message

    fetched = []
    for url in urls[:3]:  # max 3 URLs per message
        try:
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (compatible; FrappeAI/1.0)",
                "Accept": "text/html,text/plain,*/*",
            }, allow_redirects=True)
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "")
            if "json" in content_type:
                text = resp.text[:8000]
            elif "html" in content_type or not content_type:
                text = _html_to_text(resp.text)[:8000]
            else:
                text = resp.text[:8000]
            fetched.append(f"--- Contenuto di {url} ---\n{text}")
        except Exception as e:
            fetched.append(f"--- {url} --- (errore: {e})")

    if fetched:
        message = message + "\n\n" + "\n\n".join(fetched)
    return message


def _html_to_text(html: str) -> str:
    """Strip HTML tags and collapse whitespace to extract readable text."""
    # Remove scripts, styles, and head
    html = re.sub(r'<(script|style|head)[^>]*>[\s\S]*?</\1>', ' ', html, flags=re.IGNORECASE)
    # Remove all tags
    text = re.sub(r'<[^>]+>', ' ', html)
    # Decode common entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') \
               .replace('&quot;', '"').replace('&#39;', "'").replace('&nbsp;', ' ')
    # Collapse whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


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
    if provider in ("Claude Code (locale)", "Claude Code (local)"):
        return _call_claude_code(messages)
    elif provider == "Claude (Anthropic)":
        return _call_anthropic(api_key, model, messages)
    elif provider == "OpenAI":
        return _call_openai_compatible("https://api.openai.com/v1/chat/completions", api_key, model, messages)
    else:
        # OpenRouter (default)
        return _call_openai_compatible("https://openrouter.ai/api/v1/chat/completions", api_key, model, messages)


def _call_claude_code(messages):
    """Call Claude via the local claude CLI (no API key required)."""
    # Build the prompt: system + conversation history + current message
    parts = []
    for m in messages:
        if m["role"] == "system":
            parts.append(f"[System: {m['content']}]")
        elif m["role"] == "user":
            parts.append(f"User: {m['content']}")
        elif m["role"] == "assistant":
            parts.append(f"Assistant: {m['content']}")

    prompt = "\n".join(parts)

    try:
        result = subprocess.run(
            ["/usr/bin/claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            frappe.throw(_("Claude Code error: {0}").format(result.stderr[:300]))
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        frappe.throw(_("Claude Code timed out after 120 seconds."))
    except FileNotFoundError:
        frappe.throw(_("Claude Code CLI not found at /usr/bin/claude."))


def _call_anthropic(api_key, model, messages):
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
