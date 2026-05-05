import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "list_doctypes",
		"description": "List DocTypes the current user has read access to, optionally filtered by module.",
		"parameters": {
			"type": "object",
			"properties": {
				"module": {"type": "string", "description": "Filter by app module name (optional)"},
			},
			"required": [],
		},
	},
}


def execute(args: dict, user: str) -> dict:
	try:
		filters = {"istable": 0}
		if args.get("module"):
			filters["module"] = args["module"]

		all_doctypes = frappe.get_list(
			"DocType",
			filters=filters,
			fields=["name", "module"],
			limit=500,
			ignore_permissions=True,
		)

		permitted = []
		for dt in all_doctypes:
			try:
				if frappe.has_permission(dt["name"], "read", user=user):
					permitted.append(dt)
			except Exception:
				pass

		return {"doctypes": permitted}
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "list_doctypes tool error")
		return {"error": f"Could not list doctypes: {exc!s}"}


register_tool("list_doctypes", SCHEMA, execute)
