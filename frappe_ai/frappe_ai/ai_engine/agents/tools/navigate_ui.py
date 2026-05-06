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
			"Do NOT use this for data queries — use search_documents or get_document instead."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"action": {
					"type": "string",
					"enum": ["list", "form", "new_form", "report", "workspace"],
					"description": (
						"The navigation action: "
						"'list' = open the list view of a DocType; "
						"'form' = open a specific existing document; "
						"'new_form' = open a blank new-document form; "
						"'report' = open a query/script report; "
						"'workspace' = open a Frappe workspace/module page."
					),
				},
				"doctype": {
					"type": "string",
					"description": "The DocType name (required for list, form, new_form). Title-cased, e.g. 'Sales Invoice', 'Item', 'Customer'.",
				},
				"name": {
					"type": "string",
					"description": "Document name/ID — required for 'form' action only (e.g. 'SINV-2026-00042').",
				},
				"report_name": {
					"type": "string",
					"description": "Report name — required for 'report' action (e.g. 'General Ledger', 'Accounts Receivable').",
				},
				"workspace": {
					"type": "string",
					"description": "Workspace or module name — required for 'workspace' action (e.g. 'Accounting', 'Stock', 'HR').",
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


def execute(args: dict, user: str) -> dict:
	action = (args.get("action") or "").strip()
	doctype = (args.get("doctype") or "").strip()
	name = (args.get("name") or "").strip()
	report_name = (args.get("report_name") or "").strip()
	workspace = (args.get("workspace") or "").strip()
	filters = args.get("filters") or {}

	# ── Validate action ────────────────────────────────────────────────────────
	valid_actions = {"list", "form", "new_form", "report", "workspace"}
	if action not in valid_actions:
		return {"error": f"Unknown action '{action}'. Must be one of: {', '.join(sorted(valid_actions))}."}

	# ── Permission + existence checks ──────────────────────────────────────────
	if action in ("list", "form", "new_form"):
		if not doctype:
			return {"error": f"'doctype' is required for action '{action}'."}
		if not frappe.db.exists("DocType", doctype):
			return {"error": f"DocType '{doctype}' does not exist."}
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
		workspace = _WORKSPACE_ALIASES.get(workspace.lower(), workspace)

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

	# Human-readable confirmation returned to the LLM (included in its reply)
	label = _human_label(action, doctype, name, report_name, workspace)
	return {
		"ui_action": payload,
		"message": f"Navigating to {label}.",
	}


def _human_label(action, doctype, name, report_name, workspace) -> str:
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
	return action


register_tool("navigate_ui", SCHEMA, execute)
