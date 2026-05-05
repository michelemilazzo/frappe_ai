import time

import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "search_documents",
		"description": "Search records in any Frappe DocType the user has access to.",
		"parameters": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string", "description": "The DocType name to search"},
				"filters": {"type": "object", "description": "Frappe-style filters dict, e.g. {\"status\": \"Open\"}."},
				"fields": {
					"type": "array",
					"items": {"type": "string"},
					"description": "List of field names to return (e.g. ['name', 'status']). Defaults to ['name'].",
				},
				"limit": {
					"type": "integer",
					"description": "Max number of records to return (1–50). Defaults to 20.",
				},
				"order_by": {
					"type": "string",
					"description": "ORDER BY clause, e.g. 'modified desc'.",
				},
			},
			"required": ["doctype"],
		},
	},
}


def execute(args: dict, user: str) -> dict:
	start_ms = time.monotonic()
	doctype = args.get("doctype", "")
	filters = args.get("filters") or {}
	fields = args.get("fields") or ["name"]
	limit = min(int(args.get("limit") or 20), 50)
	order_by = args.get("order_by") or "modified desc"

	permitted = False
	records = []
	error = None

	try:
		if not frappe.has_permission(doctype, "read", user=user):
			raise PermissionError(f"You do not have read access to {doctype}.")

		permitted = True
		safe_fields = [f for f in fields if not str(f).startswith("_")]
		if not safe_fields:
			safe_fields = ["name"]

		records = frappe.get_list(
			doctype,
			filters=filters,
			fields=safe_fields,
			limit=limit,
			order_by=order_by,
			ignore_permissions=False,
		)
	except PermissionError as exc:
		error = str(exc)
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "search_documents tool error")
		error = f"Error searching {doctype}: {exc!s}"

	_log_call(
		user=user,
		tool_name="search_documents",
		doctype=doctype,
		filters=filters,
		records_returned=len(records),
		was_permitted=permitted,
		execution_ms=int((time.monotonic() - start_ms) * 1000),
	)

	if error:
		return {"error": error, "doctype": doctype}

	return {"data": [r for r in records], "count": len(records), "doctype": doctype}


def _log_call(user, tool_name, doctype, filters, records_returned, was_permitted, execution_ms):
	try:
		import json

		doc = frappe.new_doc("AI Tool Call Log")
		doc.user = user
		doc.tool_name = tool_name
		doc.doctype_accessed = doctype
		doc.filters_used = json.dumps(filters)
		doc.records_returned = records_returned
		doc.was_permitted = 1 if was_permitted else 0
		doc.execution_ms = execution_ms
		doc.timestamp = frappe.utils.now()
		doc.insert(ignore_permissions=True)
	except Exception:
		pass


register_tool("search_documents", SCHEMA, execute)
