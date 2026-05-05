import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "get_user_context",
		"description": "Get context about the current user: name, roles, company, date, and system info.",
		"parameters": {
			"type": "object",
			"properties": {},
			"required": [],
		},
	},
}


def execute(args: dict, user: str) -> dict:
	try:
		user_doc = frappe.get_doc("User", user)
		roles = [r.role for r in user_doc.roles if r.role]

		defaults = frappe.defaults.get_defaults(user)
		company = defaults.get("company", "")
		currency = defaults.get("currency", "")

		timezone = frappe.db.get_value("User", user, "time_zone") or frappe.utils.get_system_timezone()

		return {
			"full_name": user_doc.full_name or user,
			"email": user,
			"roles": roles,
			"default_company": company,
			"default_currency": currency,
			"today": frappe.utils.today(),
			"frappe_version": frappe.__version__,
			"timezone": timezone,
		}
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "get_user_context tool error")
		return {"error": f"Could not load user context: {exc!s}"}


register_tool("get_user_context", SCHEMA, execute)
