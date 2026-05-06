import re

import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "navigate_ui",
		"description": (
			"Navigate the Frappe desk UI for the user: open a list view, open a specific document, "
			"open a form to create a new document, open a report, or open a module/workspace. "
			"Use this when the user says 'go to', 'open', 'take me to', 'show me', or 'navigate to' "
			"a page, list, document, or module in the application. "
			"Fuzzy name resolution is applied — partial or approximate names are accepted. "
			"Do NOT use this for data queries — use search_documents or get_document instead."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"action": {
					"type": "string",
					"enum": ["list", "form", "new_form", "report", "workspace", "page"],
					"description": (
						"The navigation action: "
						"'list' = open the list view of a DocType; "
						"'form' = open a specific existing document; "
						"'new_form' = open a blank new-document form; "
						"'report' = open a query/script report; "
						"'workspace' = open a Frappe workspace/module page; "
						"'page' = open a custom Frappe page by name or slug."
					),
				},
				"doctype": {
					"type": "string",
					"description": "The DocType name (required for list, form, new_form). Title-cased, e.g. 'Sales Invoice', 'Item', 'Customer'. Fuzzy match applied.",
				},
				"name": {
					"type": "string",
					"description": "Document name/ID — required for 'form' action only (e.g. 'SINV-2026-00042').",
				},
				"report_name": {
					"type": "string",
					"description": "Report name — required for 'report' action (e.g. 'General Ledger', 'Accounts Receivable'). Fuzzy match applied.",
				},
				"workspace": {
					"type": "string",
					"description": "Workspace or module name — required for 'workspace' action (e.g. 'Accounting', 'Stock', 'HR'). Fuzzy match applied.",
				},
				"page": {
					"type": "string",
					"description": "Custom page name or slug — required for 'page' action (e.g. 'timesheet-log-heatmap-view', 'Activity'). Fuzzy match applied.",
				},
				"filters": {
					"type": "object",
					"description": "Optional key-value filters to pre-apply on list view (e.g. {\"status\": \"Open\", \"company\": \"Acme\"}).",
				},
			},
			"required": ["action"],
		},
	},
}

# Map of well-known workspace name variants → canonical Frappe workspace slugs
_WORKSPACE_ALIASES = {
	"accounting": "Accounting",
	"accounts": "Accounting",
	"finance": "Accounting",
	"stock": "Stock",
	"inventory": "Stock",
	"warehouse": "Stock",
	"hr": "HR",
	"human resources": "HR",
	"payroll": "Payroll",
	"purchase": "Buying",
	"buying": "Buying",
	"sales": "Selling",
	"selling": "Selling",
	"crm": "CRM",
	"manufacturing": "Manufacturing",
	"projects": "Projects",
	"project": "Projects",
	"support": "Support",
	"assets": "Assets",
	"asset": "Assets",
	"loans": "Loan Management",
}


# ── Fuzzy helpers ─────────────────────────────────────────────────────────────

def _tokenize(s: str) -> set:
	"""Split string into lowercase word tokens, stripping punctuation."""
	return set(re.findall(r"[a-z0-9]+", s.lower()))


def _fuzzy_score(query: str, candidate: str) -> float:
	"""
	Return a score 0–1 for how well `candidate` matches `query`.
	Uses token overlap + substring bonus + acronym bonus.
	"""
	q = query.lower().strip()
	c = candidate.lower().strip()

	# Exact match
	if q == c:
		return 1.0

	# Normalize hyphens/underscores for comparison
	q_norm = re.sub(r"[-_]", " ", q)
	c_norm = re.sub(r"[-_]", " ", c)

	if q_norm == c_norm:
		return 0.99

	# Substring match
	substr_score = 0.0
	if q_norm in c_norm:
		substr_score = 0.8
	elif c_norm in q_norm:
		substr_score = 0.7

	# Token overlap (Jaccard)
	q_tokens = _tokenize(q_norm)
	c_tokens = _tokenize(c_norm)
	if q_tokens and c_tokens:
		inter = len(q_tokens & c_tokens)
		union = len(q_tokens | c_tokens)
		token_score = inter / union if union else 0.0
	else:
		token_score = 0.0

	# Acronym: e.g. "pms" matches "Project Management System"
	acronym = "".join(w[0] for w in c_norm.split() if w)
	acro_score = 0.6 if acronym == q.replace(" ", "").lower() else 0.0

	return max(substr_score, token_score, acro_score)


def _best_match(query: str, candidates: list, threshold: float = 0.25) -> str | None:
	"""Return the candidate with the highest fuzzy score above threshold, or None."""
	if not query or not candidates:
		return None
	scored = [(c, _fuzzy_score(query, c)) for c in candidates]
	scored.sort(key=lambda x: x[1], reverse=True)
	best, score = scored[0]
	return best if score >= threshold else None


def _resolve_doctype(raw: str) -> str:
	"""Resolve a possibly-fuzzy DocType name. Returns canonical name or raw."""
	if not raw:
		return raw
	# Exact match (case-insensitive)
	existing = frappe.db.get_value("DocType", {"name": raw}, "name")
	if existing:
		return existing
	# Case-insensitive exact
	existing = frappe.db.get_value("DocType", {"name": ["=", raw]}, "name", order_by="name asc")
	if existing:
		return existing
	# Fuzzy: fetch all visible DocType names (limit 500)
	all_dt = [r[0] for r in frappe.db.sql("SELECT name FROM `tabDocType` WHERE istable=0 LIMIT 500")]
	match = _best_match(raw, all_dt)
	return match or raw


def _resolve_report(raw: str) -> str:
	"""Resolve a possibly-fuzzy Report name."""
	if not raw:
		return raw
	existing = frappe.db.get_value("Report", {"name": ["=", raw]}, "name")
	if existing:
		return existing
	all_reports = [r[0] for r in frappe.db.sql("SELECT name FROM `tabReport` WHERE disabled=0 LIMIT 500")]
	match = _best_match(raw, all_reports)
	return match or raw


def _resolve_workspace(raw: str) -> str:
	"""Resolve via alias map first, then fuzzy against DB."""
	if not raw:
		return raw
	alias = _WORKSPACE_ALIASES.get(raw.lower())
	if alias:
		return alias
	existing = frappe.db.get_value("Workspace", {"name": ["=", raw]}, "name")
	if existing:
		return existing
	all_ws = [r[0] for r in frappe.db.sql("SELECT name FROM `tabWorkspace` WHERE public=1 OR for_user='' LIMIT 300")]
	match = _best_match(raw, all_ws)
	return match or raw


def _resolve_page(raw: str) -> str:
	"""Resolve a custom Frappe Page name or slug via fuzzy matching."""
	if not raw:
		return raw
	# Normalize: "timesheet log heatmap page" → strip trailing "page"
	normalized = re.sub(r"\bpage\b", "", raw, flags=re.IGNORECASE).strip()
	# Exact DB match
	existing = frappe.db.get_value("Page", {"name": ["=", raw]}, "name")
	if existing:
		return existing
	# All pages
	all_pages = [r[0] for r in frappe.db.sql("SELECT name FROM `tabPage` LIMIT 300")]
	# Try normalized first
	match = _best_match(normalized, all_pages) or _best_match(raw, all_pages)
	return match or raw


# ── Main execute ──────────────────────────────────────────────────────────────

def execute(args: dict, user: str) -> dict:
	action = (args.get("action") or "").strip()
	doctype = (args.get("doctype") or "").strip()
	name = (args.get("name") or "").strip()
	report_name = (args.get("report_name") or "").strip()
	workspace = (args.get("workspace") or "").strip()
	page = (args.get("page") or "").strip()
	filters = args.get("filters") or {}

	# ── Validate action ────────────────────────────────────────────────────────
	valid_actions = {"list", "form", "new_form", "report", "workspace", "page"}
	if action not in valid_actions:
		return {"error": f"Unknown action '{action}'. Must be one of: {', '.join(sorted(valid_actions))}."}

	# ── Fuzzy resolution ───────────────────────────────────────────────────────
	if action in ("list", "form", "new_form") and doctype:
		doctype = _resolve_doctype(doctype)

	if action == "report" and report_name:
		report_name = _resolve_report(report_name)

	if action == "workspace" and workspace:
		workspace = _resolve_workspace(workspace)

	if action == "page" and page:
		page = _resolve_page(page)

	# ── Permission + existence checks ──────────────────────────────────────────
	if action in ("list", "form", "new_form"):
		if not doctype:
			return {"error": f"'doctype' is required for action '{action}'."}
		if not frappe.db.exists("DocType", doctype):
			return {"error": f"DocType '{doctype}' does not exist. Could not find a close match either."}
		perm_type = "create" if action == "new_form" else "read"
		if not frappe.has_permission(doctype, perm_type, user=user):
			return {"error": f"You do not have {perm_type} permission for '{doctype}'."}
		if action == "form":
			if not name:
				return {"error": "'name' is required for action 'form'."}
			if not frappe.db.exists(doctype, name):
				return {"error": f"Document '{name}' does not exist in '{doctype}'."}
			if not frappe.has_permission(doctype, "read", doc=name, user=user):
				return {"error": f"You do not have permission to view '{name}'."}

	if action == "report":
		if not report_name:
			return {"error": "'report_name' is required for action 'report'."}

	if action == "workspace":
		if not workspace:
			return {"error": "'workspace' is required for action 'workspace'."}

	if action == "page":
		if not page:
			return {"error": "'page' is required for action 'page'."}

	# ── Build the ui_action payload the client will execute ───────────────────
	payload: dict = {"action": action}

	if action == "list":
		payload["doctype"] = doctype
		if filters:
			payload["filters"] = filters

	elif action == "form":
		payload["doctype"] = doctype
		payload["name"] = name

	elif action == "new_form":
		payload["doctype"] = doctype
		if filters:
			payload["defaults"] = filters  # pre-fill fields on new form

	elif action == "report":
		payload["report_name"] = report_name
		if filters:
			payload["filters"] = filters

	elif action == "workspace":
		payload["workspace"] = workspace

	elif action == "page":
		payload["page"] = page

	# Human-readable confirmation returned to the LLM (included in its reply)
	label = _human_label(action, doctype, name, report_name, workspace, page)
	return {
		"ui_action": payload,
		"message": f"Navigating to {label}.",
	}


def _human_label(action, doctype, name, report_name, workspace, page="") -> str:
	if action == "list":
		return f"{doctype} list"
	if action == "form":
		return f"{doctype} — {name}"
	if action == "new_form":
		return f"new {doctype} form"
	if action == "report":
		return f"'{report_name}' report"
	if action == "workspace":
		return f"'{workspace}' workspace"
	if action == "page":
		return f"'{page}' page"
	return action


register_tool("navigate_ui", SCHEMA, execute)
