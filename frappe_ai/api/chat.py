import json
import re
import subprocess
import frappe
import requests
from frappe import _

# Matches http/https URLs
_URL_RE = re.compile(r'https?://[^\s\)\]>"\',]+', re.IGNORECASE)


# Central defaults — read from common_site_config or hardcoded fallback.
# All sites share this unless overridden via AI Settings doctype.
_CENTRAL_DEFAULTS = {
    "provider": "Ollama",
    "api_key": None,
    "model": "qwen2.5:7b",
    "ollama_url": "http://10.10.0.4:11434",
    "system_prompt": "",
}


@frappe.whitelist()
def send_message(message: str, history=None):
    """Send a message to the configured AI provider and return the response."""
    if isinstance(history, str):
        try:
            history = json.loads(history)
        except (json.JSONDecodeError, TypeError):
            history = []

    settings = _get_settings()
    provider = settings.get("provider", "Ollama")

    if provider not in ("Claude Code (locale)", "Claude Code (local)", "Ollama") and not settings.get("api_key"):
        frappe.throw(_("AI API Key not configured. Go to AI Settings to configure."))

    message = _inject_url_content(message)
    system_prompt = settings.get("system_prompt", "") + "\n\n" + _frappe_context()
    messages = _build_messages(system_prompt, history or [], message)

    reply = _call_provider(
        provider=provider,
        api_key=settings.get("api_key"),
        model=settings.get("model"),
        messages=messages,
        ollama_url=settings.get("ollama_url"),
    )

    return {"reply": reply}


def _get_settings():
    """
    Priority: AI Settings doctype (per-site) → common_site_config (per-bench) → central defaults.
    This allows central configuration without touching each site.
    """
    # Start from central defaults
    result = dict(_CENTRAL_DEFAULTS)

    # Layer 1: common_site_config (bench-wide, set once per bench)
    conf = frappe.conf
    if conf.get("frappe_ai_provider"):
        result["provider"] = conf.frappe_ai_provider
    if conf.get("frappe_ai_model"):
        result["model"] = conf.frappe_ai_model
    if conf.get("frappe_ai_api_key"):
        result["api_key"] = conf.frappe_ai_api_key
    if conf.get("frappe_ai_ollama_url"):
        result["ollama_url"] = conf.frappe_ai_ollama_url
    if conf.get("frappe_ai_system_prompt"):
        result["system_prompt"] = conf.frappe_ai_system_prompt

    # Layer 2: AI Settings doctype (per-site override)
    if frappe.db.exists("DocType", "AI Settings"):
        doc = frappe.get_single("AI Settings")
        if doc.provider:
            result["provider"] = doc.provider
        if doc.api_key:
            result["api_key"] = doc.get_password("api_key")
        if doc.model:
            result["model"] = doc.model
        if doc.system_prompt:
            result["system_prompt"] = doc.system_prompt

    return result


def _frappe_context() -> str:
    """Build a Frappe context block: site, user, installed apps, recent doctypes."""
    try:
        site = frappe.local.site or ""
        user = frappe.session.user or ""
        installed = frappe.get_installed_apps()
        modules = frappe.db.get_all("Module Def", fields=["name", "app_name"], limit=50)
        mod_list = ", ".join(f"{m.name}({m.app_name})" for m in modules)

        # Recent doctypes the user can access
        doctypes = frappe.db.get_all("DocType", filters={"issingle": 0, "istable": 0},
                                     fields=["name", "module"], limit=80)
        dt_list = ", ".join(d.name for d in doctypes)

        return (
            f"## Contesto Frappe\n"
            f"- Sito: {site}\n"
            f"- Utente: {user}\n"
            f"- App installate: {', '.join(installed)}\n"
            f"- Moduli: {mod_list}\n"
            f"- DocType disponibili (sample): {dt_list}\n"
            f"Puoi rispondere a domande su questi dati e aiutare l'utente a navigare il sistema."
        )
    except Exception:
        return ""


@frappe.whitelist()
def query_frappe(doctype: str, filters: str = "{}", fields: str = '["name"]', limit: int = 20):
    """Execute a safe read-only query on a Frappe DocType and return results."""
    try:
        filters_dict = json.loads(filters) if isinstance(filters, str) else filters
        fields_list = json.loads(fields) if isinstance(fields, str) else fields
        limit = min(int(limit), 100)
        results = frappe.db.get_all(doctype, filters=filters_dict, fields=fields_list, limit=limit)
        return {"results": results, "count": len(results)}
    except Exception as e:
        frappe.throw(_("Errore query: {0}").format(str(e)))


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


def _call_provider(provider, api_key, model, messages, ollama_url=None):
    if provider in ("Claude Code (locale)", "Claude Code (local)"):
        return _call_claude_code(messages)
    elif provider == "Ollama":
        base = (ollama_url or _CENTRAL_DEFAULTS["ollama_url"]).rstrip("/")
        return _call_ollama(base, model or _CENTRAL_DEFAULTS["model"], messages)
    elif provider == "Claude (Anthropic)":
        return _call_anthropic(api_key, model, messages)
    elif provider == "OpenAI":
        return _call_openai_compatible("https://api.openai.com/v1/chat/completions", api_key, model, messages)
    else:
        # OpenRouter (default)
        return _call_openai_compatible("https://openrouter.ai/api/v1/chat/completions", api_key, model, messages)


def _call_ollama(base_url, model, messages):
    """Call Ollama via its OpenAI-compatible /v1/chat/completions endpoint."""
    system_content = ""
    filtered = []
    for m in messages:
        if m["role"] == "system":
            system_content = m["content"]
        else:
            filtered.append(m)

    if system_content:
        filtered = [{"role": "system", "content": system_content}] + filtered

    try:
        resp = requests.post(
            f"{base_url}/v1/chat/completions",
            json={"model": model, "messages": filtered, "stream": False},
            headers={"Content-Type": "application/json"},
            timeout=120,
        )
    except requests.exceptions.ConnectionError:
        frappe.throw(_("Ollama non raggiungibile su {0}. Verifica che il servizio sia attivo.").format(base_url))

    if not resp.ok:
        frappe.throw(_("Ollama error {0}: {1}").format(resp.status_code, resp.text[:300]))

    return resp.json()["choices"][0]["message"]["content"]


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


_OPENROUTER_FALLBACKS = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "google/gemma-4-31b-it:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "qwen/qwen3-coder:free",
    "meta-llama/llama-3.2-3b-instruct:free",
]


def _call_openai_compatible(url, api_key, model, messages):
    site_url = frappe.utils.get_url()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": site_url,
        "X-Title": "Frappe AI",
    }

    # Build candidate list: configured model first, then fallbacks (deduped)
    is_openrouter = "openrouter.ai" in url
    candidates = [model]
    if is_openrouter:
        for fb in _OPENROUTER_FALLBACKS:
            if fb not in candidates:
                candidates.append(fb)

    last_error = None
    for candidate in candidates:
        resp = requests.post(
            url,
            json={"model": candidate, "messages": messages, "max_tokens": 1024},
            headers=headers,
            timeout=60,
        )
        if resp.status_code in (429, 404):
            last_error = f"{resp.status_code} ({candidate})"
            continue
        if not resp.ok:
            frappe.throw(_("AI provider error {0}: {1}").format(resp.status_code, resp.text[:300]))
        try:
            data = resp.json()
        except Exception:
            frappe.throw(_("AI provider returned invalid response (status {0}): {1}").format(resp.status_code, resp.text[:300]))
        return data["choices"][0]["message"]["content"]

    frappe.throw(_("All AI models are rate-limited. Try again in a few seconds. Last error: {0}").format(last_error))
