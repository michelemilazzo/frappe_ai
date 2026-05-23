import json
import os
import re
import subprocess
import tempfile
import frappe
import requests
from frappe import _
from pathlib import Path

# Matches http/https URLs
_URL_RE = re.compile(r'https?://[^\s\)\]>"\',]+', re.IGNORECASE)

# Action block regex: ```action\n{...}\n```
_ACTION_RE = re.compile(r'```action\s*\n(\{[\s\S]*?\})\s*\n```', re.IGNORECASE)

# Users allowed to execute server actions
_ACTION_ALLOWED_USERS = {"Administrator", "admin@onekeyco.com"}

# Safe shell commands prefix whitelist
_SAFE_SHELL_PREFIXES = (
    "bench ", "python ", "python3 ", "pip ", "ls ", "cat ", "grep ",
    "find ", "echo ", "mkdir ", "cp ", "mv ", "rm ", "git ", "cd ",
    "yarn ", "npm ", "node ",
)


# Central defaults — read from common_site_config or hardcoded fallback.
# All sites share this unless overridden via AI Settings doctype.
_CENTRAL_DEFAULTS = {
    "provider": "Ollama",
    "api_key": None,
    "model": "qwen2.5:7b",
    "ollama_url": "http://10.10.0.4:11434",
    "system_prompt": "",
}


def _check_action_permission():
    if frappe.session.user not in _ACTION_ALLOWED_USERS:
        frappe.throw(_("Azione non consentita. Riservata ad Administrator e admin@onekeyco.com."))


def _bench_root() -> Path:
    return Path(frappe.utils.get_bench_path())


def _safe_path(path: str) -> Path:
    """Resolve path, restrict to bench or /tmp."""
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = _bench_root() / p
    p = p.resolve()
    bench = _bench_root().resolve()
    if not (str(p).startswith(str(bench)) or str(p).startswith("/tmp")):
        frappe.throw(_("Path non consentito: {0}").format(path))
    return p


@frappe.whitelist()
def execute_action(action_type: str, params: str = "{}"):
    """Execute a real server action. Reserved for Administrator and admin@onekeyco.com."""
    _check_action_permission()
    p = json.loads(params) if isinstance(params, str) else (params or {})

    if action_type == "write_file":
        path = _safe_path(p["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(p["content"], encoding="utf-8")
        return {"ok": True, "path": str(path), "bytes": len(p["content"])}

    elif action_type == "read_file":
        path = _safe_path(p["path"])
        if not path.exists():
            frappe.throw(_("File non trovato: {0}").format(p["path"]))
        content = path.read_text(encoding="utf-8", errors="replace")
        return {"ok": True, "path": str(path), "content": content[:50000]}

    elif action_type == "list_files":
        path = _safe_path(p.get("path", "."))
        if not path.is_dir():
            frappe.throw(_("Directory non trovata: {0}").format(p.get("path")))
        items = [{"name": f.name, "type": "dir" if f.is_dir() else "file", "size": f.stat().st_size if f.is_file() else 0}
                 for f in sorted(path.iterdir())[:200]]
        return {"ok": True, "path": str(path), "items": items}

    elif action_type == "run_python":
        code = p.get("code", "")
        # Execute in a subprocess with bench python
        bench = _bench_root()
        py = bench / "env" / "bin" / "python"
        if not py.exists():
            py = Path("python3")
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write(code)
            tmp = f.name
        try:
            result = subprocess.run(
                [str(py), tmp],
                capture_output=True, text=True, timeout=30,
                cwd=str(bench),
            )
        finally:
            os.unlink(tmp)
        return {"ok": result.returncode == 0, "stdout": result.stdout[:10000], "stderr": result.stderr[:3000], "rc": result.returncode}

    elif action_type == "run_shell":
        cmd = p.get("cmd", "")
        if not any(cmd.lstrip().startswith(pfx) for pfx in _SAFE_SHELL_PREFIXES):
            frappe.throw(_("Comando non consentito: {0}").format(cmd.split()[0] if cmd else ""))
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60,
            cwd=str(_bench_root()),
        )
        return {"ok": result.returncode == 0, "stdout": result.stdout[:10000], "stderr": result.stderr[:3000], "rc": result.returncode}

    elif action_type == "bench_cmd":
        site = p.get("site") or frappe.local.site
        bench_cmd = p.get("cmd", "")
        full = f"bench --site {site} {bench_cmd}"
        result = subprocess.run(
            full, shell=True, capture_output=True, text=True, timeout=120,
            cwd=str(_bench_root()),
        )
        return {"ok": result.returncode == 0, "stdout": result.stdout[:10000], "stderr": result.stderr[:3000]}

    else:
        frappe.throw(_("Azione non supportata: {0}").format(action_type))


def _auto_execute_actions(reply: str) -> tuple[str, list[dict]]:
    """Parse and execute ```action {...}``` blocks from AI reply. Returns (cleaned_reply, results)."""
    if frappe.session.user not in _ACTION_ALLOWED_USERS:
        return reply, []

    results = []
    def _run_block(m):
        try:
            action = json.loads(m.group(1))
            atype = action.pop("action", "write_file")
            res = execute_action(atype, json.dumps(action))
            results.append({"action": atype, **res})
            status = "✅ eseguito" if res.get("ok") else "❌ errore"
            if atype == "write_file":
                return f"`{res.get('path')}` — {status} ({res.get('bytes', 0)} bytes)"
            elif atype in ("run_python", "run_shell", "bench_cmd"):
                out = (res.get("stdout") or "").strip()[:500]
                return f"{status}\n```\n{out}\n```" if out else status
            return status
        except Exception as e:
            results.append({"error": str(e)})
            return f"❌ errore azione: {e}"

    cleaned = _ACTION_RE.sub(_run_block, reply)
    return cleaned, results


@frappe.whitelist()
def send_message(message: str, history=None, agent_mode: int = 0):
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

    # Build system prompt — extend with agent instructions when enabled
    base_prompt = settings.get("system_prompt", "") + "\n\n" + _frappe_context()
    is_agent = int(agent_mode) == 1 and frappe.session.user in _ACTION_ALLOWED_USERS
    if is_agent:
        base_prompt += "\n\n" + _agent_instructions()

    messages = _build_messages(base_prompt, history or [], message)

    reply = _call_provider(
        provider=provider,
        api_key=settings.get("api_key"),
        model=settings.get("model"),
        messages=messages,
        ollama_url=settings.get("ollama_url"),
    )

    actions_executed = []
    if is_agent:
        reply, actions_executed = _auto_execute_actions(reply)

    return {"reply": reply, "actions": actions_executed, "agent_mode": is_agent}


def _agent_instructions() -> str:
    bench = str(_bench_root())
    site = frappe.local.site or ""
    return f"""## Modalità Agent — ESECUZIONE REALE
Puoi scrivere e modificare file direttamente sul server.
Per eseguire un'azione includi un blocco ```action``` nel tuo messaggio nel formato JSON:

```action
{{"action": "write_file", "path": "apps/myapp/myapp/mymodule.py", "content": "# contenuto del file\\n..."}}
```

Azioni disponibili:
- **write_file**: `{{"action":"write_file","path":"<relativo a bench o assoluto>","content":"<testo>"}}`
- **read_file**: `{{"action":"read_file","path":"<path>"}}`
- **list_files**: `{{"action":"list_files","path":"<dir>"}}`
- **run_python**: `{{"action":"run_python","code":"<codice python>"}}`
- **run_shell**: `{{"action":"run_shell","cmd":"<comando>"}}` (solo comandi: bench, python, pip, ls, cat, grep, find, git, yarn, npm)
- **bench_cmd**: `{{"action":"bench_cmd","site":"{site}","cmd":"<sottocomando bench>"}}`

Bench path: `{bench}`
Sito corrente: `{site}`

Regole:
- Usa path relativi rispetto al bench quando possibile
- Prima di scrivere un file mostra cosa farai
- Puoi includere più blocchi ```action``` in una risposta
- I risultati vengono mostrati all'utente automaticamente"""


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
        if getattr(doc, "ollama_url", None):
            result["ollama_url"] = doc.ollama_url

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
