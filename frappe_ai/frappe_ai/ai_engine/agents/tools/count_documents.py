import time

import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "count_documents",
		"description": "Count records in a DocType matching optional filters.",
		"parameters": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string", "description": "The DocType name"},
				"filters": {"type": "object", "description": "Frappe-style filters dict, e.g. {\"status\": \"Open\"}."},
			},
			"required": ["doctype"],
		},
	},
}


def execute(args: dict, user: str) -> dict:
	start_ms = time.monotonic()
	doctype = args.get("doctype", "")
	filters = args.get("filters") or {}
	permitted = False
	count = 0
	error = None

	try:
		if not frappe.has_permission(doctype, "read", user=user):
			raise PermissionError(f"You do not have read access to {doctype}.")

		permitted = True
		count = frappe.db.count(doctype, filters)
	except PermissionError as exc:
		error = str(exc)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "count_documents tool error")
		error = f"Error counting {doctype}: {exc!s}"

	_log_call(
		user=user,
		doctype=doctype,
		was_permitted=permitted,
		execution_ms=int((time.monotonic() - start_ms) * 1000),
	)

	if error:
		return {"error": error, "doctype": doctype}

	return {"count": count, "doctype": doctype}


def _log_call(user, doctype, was_permitted, execution_ms):
	try:
		import json

		doc = frappe.new_doc("AI Tool Call Log")
		doc.user = user
		doc.tool_name = "count_documents"
		doc.doctype_accessed = doctype
		doc.filters_used = json.dumps({})
		doc.was_permitted = 1 if was_permitted else 0
		doc.execution_ms = execution_ms
		doc.timestamp = frappe.utils.now()
		doc.insert(ignore_permissions=True)
	except Exception:
		pass


register_tool("count_documents", SCHEMA, execute)
