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

# Users allowed to execute invasive server actions
_ACTION_ALLOWED_USERS = {"Administrator", "admin@onekeyco.com"}

# Non-invasive actions allowed to authenticated users
_NON_INVASIVE_ACTIONS = {
    "create_customer",
    "create_web_page",
    "create_webshop_item",
    "translate_doc_fields",
    "generate_contract",
    "publish_to_press_marketplace",
}

_INVASIVE_ACTIONS = {
    "write_file",
    "read_file",
    "list_files",
    "run_python",
    "run_shell",
    "bench_cmd",
    "install_app_if_missing",
    "ensure_app_available_everywhere",
}

# Safe shell commands prefix whitelist
_SAFE_SHELL_PREFIXES = (
    "bench ", "python ", "python3 ", "pip ", "ls ", "cat ", "grep ",
    "find ", "echo ", "mkdir ", "cp ", "mv ", "git ", "cd ",
    "yarn ", "npm ", "node ",
)


# Central defaults — read from common_site_config or hardcoded fallback.
# All sites share this unless overridden via AI Settings doctype.
_CENTRAL_DEFAULTS = {
    "provider": "AI-MMOS-Core",
    "api_key": None,
    "model": "qwen2.5:7b",
    "ollama_url": "http://10.10.0.4:11434",
    "core_chat_path": "/v1/chat/completions",
    "system_prompt": "",
    "github_owner": "michelemilazzo",
    "github_token": None,
    "simple_task_provider": "OpenRouter",
    "simple_task_model": "meta-llama/llama-3.2-3b-instruct:free",
    "fallback_provider": "Ollama",
    "fallback_model": "qwen2.5:7b",
}

_MEMORY_LIMIT = 40


def _memory_cache_key() -> str:
    user = frappe.session.user or "Guest"
    site = frappe.local.site or "default"
    if user == "Guest":
        sid = getattr(frappe.session, "sid", None) or "anon"
        return f"frappe_ai:memory:{site}:{user}:{sid}"
    return f"frappe_ai:memory:{site}:{user}"


@frappe.whitelist(allow_guest=True)
def get_memory():
    """Return persisted chat memory for current user/site."""
    raw = frappe.cache().get_value(_memory_cache_key())
    if not raw:
        return {"history": [], "agent_mode": 0}
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = {}
    history = data.get("history") if isinstance(data, dict) else []
    if not isinstance(history, list):
        history = []
    return {"history": history[-_MEMORY_LIMIT:], "agent_mode": int(bool((data or {}).get("agent_mode")))}


@frappe.whitelist(allow_guest=True)
def save_memory(history=None, agent_mode: int = 0):
    """Persist chat memory for current user/site."""
    if isinstance(history, str):
        try:
            history = json.loads(history)
        except Exception:
            history = []
    history = history if isinstance(history, list) else []
    cleaned = []
    for entry in history[-_MEMORY_LIMIT:]:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = entry.get("content")
        if role in ("user", "assistant", "system") and isinstance(content, str):
            cleaned.append({"role": role, "content": content[:10000]})
    payload = {"history": cleaned, "agent_mode": int(bool(agent_mode))}
    frappe.cache().set_value(_memory_cache_key(), json.dumps(payload))
    return {"ok": True, "count": len(cleaned)}


def _check_action_permission(action_type: str):
    user = frappe.session.user or "Guest"
    if action_type in _INVASIVE_ACTIONS:
        if user not in _ACTION_ALLOWED_USERS:
            frappe.throw(_("Azione invasiva non consentita. Riservata ad Administrator e admin@onekeyco.com."))
        return
    if action_type in _NON_INVASIVE_ACTIONS:
        if user == "Guest":
            frappe.throw(_("Login richiesto per questa azione."))
        return
    # Unknown action: keep strict.
    if user not in _ACTION_ALLOWED_USERS:
        frappe.throw(_("Azione non consentita."))


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


def _coerce_dict(raw):
    if isinstance(raw, str):
        return json.loads(raw or "{}")
    return raw or {}


def _is_simple_task(message: str) -> bool:
    msg = (message or "").strip().lower()
    if not msg:
        return True
    if len(msg) > 350:
        return False
    complex_markers = (
        "codice", "code", "script", "python", "sql", "api", "deploy", "install",
        "migra", "migrate", "server", "bench", "errore", "error", "debug",
        "contratto", "firma", "webshop", "customer", "doctype",
    )
    return not any(k in msg for k in complex_markers)


def _github_headers(token: str | None):
    if not token:
        return {}
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _discover_repo_for_app(app: str, owner: str, token: str | None) -> str | None:
    direct = f"https://github.com/{owner}/{app}"
    if subprocess.run(["git", "ls-remote", direct], capture_output=True, text=True).returncode == 0:
        return direct

    search_url = "https://api.github.com/search/repositories"
    params = {"q": f"{app} in:name", "sort": "stars", "order": "desc", "per_page": 5}
    resp = requests.get(search_url, params=params, headers=_github_headers(token), timeout=20)
    if not resp.ok:
        return None
    for item in resp.json().get("items", []):
        full_name = item.get("full_name", "")
        if full_name:
            return f"https://github.com/{full_name}"
    return None


def _fork_repo_if_needed(repo_url: str, owner: str, token: str | None) -> str:
    if not repo_url.startswith("https://github.com/"):
        return repo_url
    path = repo_url.replace("https://github.com/", "").strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    src_owner, src_repo = path.split("/", 1)
    if src_owner.lower() == owner.lower():
        return f"https://github.com/{owner}/{src_repo}"
    if not token:
        return repo_url

    fork_api = f"https://api.github.com/repos/{src_owner}/{src_repo}/forks"
    payload = {"name": src_repo, "default_branch_only": True}
    requests.post(fork_api, json=payload, headers=_github_headers(token), timeout=30)

    fork_repo = f"https://github.com/{owner}/{src_repo}"
    for _ in range(15):
        probe = requests.get(
            f"https://api.github.com/repos/{owner}/{src_repo}",
            headers=_github_headers(token),
            timeout=15,
        )
        if probe.ok:
            return fork_repo
        frappe.utils.sleep(2)
    return repo_url


def _install_app_if_missing(payload: dict) -> dict:
    data = _coerce_dict(payload)
    app = (data.get("app") or "").strip()
    if not app:
        frappe.throw(_("app obbligatoria"))

    settings = _get_settings()
    owner = data.get("github_owner") or settings.get("github_owner") or "michelemilazzo"
    token = data.get("github_token") or settings.get("github_token")
    repo = (data.get("repo") or "").strip() or _discover_repo_for_app(app, owner, token)
    if not repo:
        frappe.throw(_("Repository non trovato per app: {0}").format(app))

    repo_for_install = _fork_repo_if_needed(repo, owner, token)
    branch = (data.get("branch") or "main").strip()
    bench = _bench_root()

    app_dir = bench / "apps" / app
    installed_now = False
    if not app_dir.exists():
        cmd = ["bench", "get-app", "--branch", branch, app, repo_for_install]
        res = subprocess.run(cmd, cwd=str(bench), capture_output=True, text=True, timeout=600)
        if res.returncode != 0:
            frappe.throw(_("get-app fallito: {0}").format((res.stderr or res.stdout)[-1500:]))
        installed_now = True

    site = data.get("site") or frappe.local.site
    install_on_site = int(data.get("install_on_site", 1)) == 1
    site_out = ""
    if install_on_site and site:
        cmd = ["bench", "--site", site, "install-app", app]
        res = subprocess.run(cmd, cwd=str(bench), capture_output=True, text=True, timeout=600)
        site_out = (res.stdout or "")[-1500:]
        if res.returncode != 0 and "already installed" not in (res.stderr or "").lower():
            frappe.throw(_("install-app fallito: {0}").format((res.stderr or res.stdout)[-1500:]))

    return {
        "ok": True,
        "app": app,
        "repo_source": repo,
        "repo_used": repo_for_install,
        "cloned_now": installed_now,
        "site": site,
        "site_output": site_out,
    }


def _publish_to_press_marketplace(payload: dict) -> dict:
    data = _coerce_dict(payload)
    app = (data.get("app") or "").strip()
    title = (data.get("title") or app.replace("_", " ").title()).strip()
    team = (data.get("team") or "").strip()
    if not app:
        frappe.throw(_("app obbligatoria"))
    if not team:
        frappe.throw(_("team obbligatorio"))

    source_name = data.get("source_name") or f"SRC-{app}-001"
    repository = (data.get("repository") or app).strip()
    repo_url = (data.get("repo_url") or f"https://github.com/michelemilazzo/{repository}").strip()
    branch = (data.get("branch") or "main").strip()

    if frappe.db.exists("App Source", source_name):
        src = frappe.get_doc("App Source", source_name)
    else:
        src = frappe.new_doc("App Source")
        src.name = source_name
    src.app = app
    src.app_title = title
    src.repository = repository
    src.repository_owner = "michelemilazzo"
    src.repository_url = repo_url
    src.branch = branch
    src.team = team
    src.enabled = 1
    src.public = 1
    src.insert(ignore_permissions=True) if src.is_new() else src.save(ignore_permissions=True)

    if frappe.db.exists("Marketplace App", {"app": app}):
        mp_name = frappe.db.get_value("Marketplace App", {"app": app}, "name")
        mp = frappe.get_doc("Marketplace App", mp_name)
    else:
        mp = frappe.new_doc("Marketplace App")
    mp.app = app
    mp.title = title
    mp.team = team
    mp.route = f"marketplace/apps/{app}"
    mp.published = 1
    mp.status = "Published"
    if not mp.published_on:
        mp.published_on = frappe.utils.nowdate()
    if data.get("description"):
        mp.description = data.get("description")
    mp.insert(ignore_permissions=True) if mp.is_new() else mp.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "ok": True,
        "app": app,
        "source": src.name,
        "marketplace_app": mp.name,
        "route": mp.route,
        "published": int(mp.published or 0),
    }


def _ensure_app_available_everywhere(payload: dict) -> dict:
    data = _coerce_dict(payload)
    install_res = _install_app_if_missing(data)
    publish_data = dict(data)
    publish_data.setdefault("app", install_res.get("app"))
    publish_data.setdefault("repo_url", install_res.get("repo_used"))
    publish_data.setdefault("repository", (install_res.get("repo_used") or "").rstrip("/").split("/")[-1])
    publish_res = _publish_to_press_marketplace(publish_data)
    return {
        "ok": True,
        "install": install_res,
        "publish": publish_res,
    }


def _create_customer(payload: dict) -> dict:
    data = _coerce_dict(payload)
    customer_name = data.get("customer_name") or data.get("name")
    if not customer_name:
        frappe.throw(_("customer_name obbligatorio"))
    customer = frappe.new_doc("Customer")
    customer.customer_name = customer_name
    if data.get("customer_type"):
        customer.customer_type = data.get("customer_type")
    if data.get("customer_group"):
        customer.customer_group = data.get("customer_group")
    if data.get("territory"):
        customer.territory = data.get("territory")
    if data.get("tax_id"):
        customer.tax_id = data.get("tax_id")
    customer.insert(ignore_permissions=True)

    if data.get("email_id") or data.get("phone"):
        contact = frappe.new_doc("Contact")
        contact.first_name = customer_name
        contact.email_id = data.get("email_id")
        contact.phone = data.get("phone")
        contact.append("links", {"link_doctype": "Customer", "link_name": customer.name})
        contact.insert(ignore_permissions=True)

    if data.get("address_line1") or data.get("city"):
        address = frappe.new_doc("Address")
        address.address_title = customer_name
        address.address_line1 = data.get("address_line1")
        address.address_line2 = data.get("address_line2")
        address.city = data.get("city")
        address.pincode = data.get("pincode")
        address.country = data.get("country")
        address.append("links", {"link_doctype": "Customer", "link_name": customer.name})
        address.insert(ignore_permissions=True)

    frappe.db.commit()
    return {"ok": True, "customer": customer.name}


def _create_web_page(payload: dict) -> dict:
    data = _coerce_dict(payload)
    title = data.get("title")
    route = data.get("route")
    html = data.get("html")
    if not title or not route or not html:
        frappe.throw(_("title, route, html obbligatori"))
    existing = frappe.db.get_value("Web Page", {"route": route.strip("/")}, "name")
    if existing:
        doc = frappe.get_doc("Web Page", existing)
    else:
        doc = frappe.new_doc("Web Page")
    doc.title = title
    doc.route = route.strip("/")
    doc.content_type = "HTML"
    doc.main_section = html
    doc.published = int(bool(data.get("published", 1)))
    doc.insert(ignore_permissions=True) if doc.is_new() else doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True, "web_page": doc.name, "route": doc.route}


def _create_webshop_item(payload: dict) -> dict:
    data = _coerce_dict(payload)
    item_code = data.get("item_code")
    item_name = data.get("item_name")
    if not item_code or not item_name:
        frappe.throw(_("item_code e item_name obbligatori"))
    if frappe.db.exists("Item", item_code):
        item = frappe.get_doc("Item", item_code)
    else:
        item = frappe.new_doc("Item")
        item.item_code = item_code
    item.item_name = item_name
    item.item_group = data.get("item_group") or item.item_group or "All Item Groups"
    item.stock_uom = data.get("stock_uom") or item.stock_uom or "Nos"
    item.is_stock_item = int(bool(data.get("is_stock_item", 0)))
    item.standard_rate = float(data.get("standard_rate") or 0)
    item.description = data.get("description") or item.description
    item.published_in_website = int(bool(data.get("published_in_website", 1)))
    item.website_warehouse = data.get("website_warehouse") or item.website_warehouse
    item.insert(ignore_permissions=True) if item.is_new() else item.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True, "item": item.name}


def _translate_doc_fields(payload: dict) -> dict:
    data = _coerce_dict(payload)
    doctype = data.get("doctype")
    name = data.get("name")
    fields = data.get("fields") or []
    target_lang = data.get("target_lang", "en")
    if not doctype or not name or not isinstance(fields, list) or not fields:
        frappe.throw(_("doctype, name e fields[] obbligatori"))
    doc = frappe.get_doc(doctype, name)
    updates = {}
    for fieldname in fields:
        value = (doc.get(fieldname) or "").strip()
        if not value:
            continue
        translated = _call_provider(
            provider="Ollama",
            api_key=None,
            model=_CENTRAL_DEFAULTS["model"],
            messages=[
                {"role": "system", "content": "Traduci in modo professionale e fedele."},
                {"role": "user", "content": f"Traduci in {target_lang}: {value}"},
            ],
            ollama_url=_CENTRAL_DEFAULTS["ollama_url"],
        )
        target_field = f"{fieldname}_{target_lang}"
        if target_field in (doc.meta.get_valid_columns() or []):
            doc.set(target_field, translated.strip())
            updates[target_field] = translated.strip()
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True, "doctype": doctype, "name": name, "updated_fields": updates}


def _generate_contract(payload: dict) -> dict:
    data = _coerce_dict(payload)
    title = data.get("title") or "Contratto"
    counterparty = data.get("counterparty") or "Cliente"
    body = data.get("body") or ""
    sign_provider = data.get("sign_provider", "manual")
    content = (
        f"# {title}\n\n"
        f"Parte contraente: {counterparty}\n\n"
        f"{body}\n\n"
        "## Firma\n"
        f"- Provider: {sign_provider}\n"
        "- Stato: Bozza\n"
    )
    file_name = f"contract-{frappe.utils.now_datetime().strftime('%Y%m%d-%H%M%S')}.md"
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": file_name,
            "is_private": 1,
            "content": content,
        }
    )
    file_doc.insert(ignore_permissions=True)
    frappe.db.commit()
    return {"ok": True, "file": file_doc.file_url, "sign_provider": sign_provider, "status": "draft"}


@frappe.whitelist()
def execute_action(action_type: str, params: str = "{}"):
    """Execute a real server action. Reserved for Administrator and admin@onekeyco.com."""
    _check_action_permission(action_type)
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

    elif action_type == "create_customer":
        return _create_customer(p.get("data", p))

    elif action_type == "create_web_page":
        return _create_web_page(p.get("data", p))

    elif action_type == "create_webshop_item":
        return _create_webshop_item(p.get("data", p))

    elif action_type == "translate_doc_fields":
        return _translate_doc_fields(p.get("data", p))

    elif action_type == "generate_contract":
        return _generate_contract(p.get("data", p))

    elif action_type == "install_app_if_missing":
        return _install_app_if_missing(p.get("data", p))

    elif action_type == "publish_to_press_marketplace":
        return _publish_to_press_marketplace(p.get("data", p))

    elif action_type == "ensure_app_available_everywhere":
        return _ensure_app_available_everywhere(p.get("data", p))

    else:
        frappe.throw(_("Azione non supportata: {0}").format(action_type))


def _auto_execute_actions(reply: str) -> tuple[str, list[dict]]:
    """Parse and execute ```action {...}``` blocks from AI reply. Returns (cleaned_reply, results)."""
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


@frappe.whitelist(allow_guest=True)
def send_message(message: str, history=None, agent_mode: int = 0):
    """Send a message to the configured AI provider and return the response."""
    if isinstance(history, str):
        try:
            history = json.loads(history)
        except (json.JSONDecodeError, TypeError):
            history = []

    settings = _get_settings()
    provider = settings.get("provider", "Ollama")

    message = _inject_url_content(message)

    # Build system prompt — extend with agent instructions when enabled
    base_prompt = settings.get("system_prompt", "") + "\n\n" + _frappe_context()
    is_agent = int(agent_mode) == 1 and (frappe.session.user or "Guest") != "Guest"
    if is_agent:
        base_prompt += "\n\n" + _agent_instructions()

    messages = _build_messages(base_prompt, history or [], message)

    # Auto-routing:
    # 1) For simple tasks prefer free model provider (if configured).
    # 2) Fall back to primary provider.
    # 3) Final fallback to local Ollama.
    is_simple = _is_simple_task(message)
    primary = (provider, settings.get("model"))
    simple_route = (settings.get("simple_task_provider"), settings.get("simple_task_model"))
    final_fallback = (settings.get("fallback_provider") or "Ollama", settings.get("fallback_model") or _CENTRAL_DEFAULTS["model"])

    attempts = []
    if is_simple and simple_route[0]:
        attempts.append(simple_route)
    attempts.append(primary)
    attempts.append(final_fallback)

    seen = set()
    last_error = None
    reply = ""
    for pvd, mdl in attempts:
        key = (pvd or "", mdl or "")
        if key in seen:
            continue
        seen.add(key)
        try:
            reply = _call_provider(
                provider=pvd,
                api_key=settings.get("api_key"),
                model=mdl,
                messages=messages,
                ollama_url=settings.get("ollama_url"),
            )
            break
        except Exception as e:
            last_error = str(e)
            continue

    if not reply:
        frappe.throw(_("Nessun provider AI disponibile. Ultimo errore: {0}").format(last_error or "sconosciuto"))

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
- **create_customer**: crea Customer + Contact + Address da JSON
- **create_web_page**: crea/aggiorna pagina website (`title`, `route`, `html`)
- **create_webshop_item**: crea/aggiorna articolo webshop (Item)
- **translate_doc_fields**: traduce campi documento e scrive `<campo>_<lang>`
- **generate_contract**: genera bozza contratto (File privato), pronto per firma
- **install_app_if_missing**: cerca app (repo tuo o internet), fa fork su GitHub owner configurato, `bench get-app` e `install-app`
- **publish_to_press_marketplace**: crea/aggiorna `App Source` e `Marketplace App` in Press e pubblica su `marketplace/apps/<app>`
- **ensure_app_available_everywhere**: esegue install/fork + publish marketplace in un unico step

Bench path: `{bench}`
Sito corrente: `{site}`

Regole:
- Usa path relativi rispetto al bench quando possibile
- Prima di scrivere un file mostra cosa farai
- Puoi includere più blocchi ```action``` in una risposta
- Azioni invasive (file/shell/python/bench/install) sono consentite solo ad Administrator
- I risultati vengono mostrati all'utente automaticamente"""


def _get_settings():
    """
    Settings derived automatically from central defaults + common_site_config.
    No UI configuration required — everything comes from ai-mmos-core (Ollama).
    """
    result = dict(_CENTRAL_DEFAULTS)

    # Optional overrides via common_site_config.json (bench-wide)
    conf = frappe.conf
    if conf.get("frappe_ai_provider"):
        result["provider"] = conf.frappe_ai_provider
    if conf.get("frappe_ai_model"):
        result["model"] = conf.frappe_ai_model
    if conf.get("frappe_ai_api_key"):
        result["api_key"] = conf.frappe_ai_api_key
    if conf.get("frappe_ai_ollama_url"):
        result["ollama_url"] = conf.frappe_ai_ollama_url
    if conf.get("frappe_ai_core_chat_path"):
        result["core_chat_path"] = conf.frappe_ai_core_chat_path
    if conf.get("frappe_ai_system_prompt"):
        result["system_prompt"] = conf.frappe_ai_system_prompt
    if conf.get("frappe_ai_simple_task_provider"):
        result["simple_task_provider"] = conf.frappe_ai_simple_task_provider
    if conf.get("frappe_ai_simple_task_model"):
        result["simple_task_model"] = conf.frappe_ai_simple_task_model
    if conf.get("frappe_ai_fallback_provider"):
        result["fallback_provider"] = conf.frappe_ai_fallback_provider
    if conf.get("frappe_ai_fallback_model"):
        result["fallback_model"] = conf.frappe_ai_fallback_model

    # Optional per-site override via AI Settings doctype — silently ignored if missing/empty.
    # If explicit site config keys are set, keep them as source of truth.
    try:
        provider_locked = bool(conf.get("frappe_ai_provider"))
        model_locked = bool(conf.get("frappe_ai_model"))
        ollama_locked = bool(conf.get("frappe_ai_ollama_url"))
        prompt_locked = bool(conf.get("frappe_ai_system_prompt"))
        if frappe.db.exists("DocType", "AI Settings"):
            doc = frappe.get_single("AI Settings")
            if doc.provider and not provider_locked:
                result["provider"] = doc.provider
            if doc.model and not model_locked:
                result["model"] = doc.model
            if doc.system_prompt and not prompt_locked:
                result["system_prompt"] = doc.system_prompt
            if getattr(doc, "ollama_url", None) and not ollama_locked:
                result["ollama_url"] = doc.ollama_url
            # api_key only if explicitly saved — never raise on missing password
            try:
                if doc.api_key:
                    result["api_key"] = doc.get_password("api_key")
            except Exception:
                pass
    except Exception:
        pass

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
    # Press is orchestrator-only: always route to AI-MMOS-Core.
    base = (ollama_url or _CENTRAL_DEFAULTS["ollama_url"]).rstrip("/")
    return _call_ai_core(
        base_url=base,
        chat_path=_CENTRAL_DEFAULTS.get("core_chat_path") or "/v1/chat/completions",
        model=(model or _CENTRAL_DEFAULTS["model"]),
        messages=messages,
    )


def _call_ai_core(base_url, chat_path, model, messages):
    path = chat_path or "/v1/chat/completions"
    if not path.startswith("/"):
        path = "/" + path
    url = f"{base_url.rstrip('/')}{path}"

    candidates = [model, "qwen2.5:7b", "llama3.1:8b", "mistral:7b"]
    seen = set()
    last_error = None

    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            resp = requests.post(
                url,
                json={"model": candidate, "messages": messages, "stream": False},
                headers={"Content-Type": "application/json"},
                timeout=180,
            )
        except requests.exceptions.ConnectionError:
            frappe.throw(_("AI-MMOS-Core non raggiungibile su {0}.").format(base_url))

        if not resp.ok:
            if resp.status_code in (400, 404, 429):
                last_error = f"{resp.status_code} ({candidate})"
                continue
            frappe.throw(_("AI-MMOS-Core error {0}: {1}").format(resp.status_code, resp.text[:300]))

        try:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception:
            frappe.throw(_("AI-MMOS-Core risposta non valida (status {0}): {1}").format(resp.status_code, resp.text[:300]))

    frappe.throw(_("Nessun modello disponibile su AI-MMOS-Core. Ultimo errore: {0}").format(last_error or "unknown"))


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
