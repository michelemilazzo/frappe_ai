import time

import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "get_document",
		"description": "Retrieve a single document by DocType and name.",
		"parameters": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string", "description": "The DocType name"},
				"name": {"type": "string", "description": "The document name/ID"},
			},
			"required": ["doctype", "name"],
		},
	},
}


def execute(args: dict, user: str) -> dict:
	start_ms = time.monotonic()
	doctype = args.get("doctype", "")
	name = args.get("name", "")
	permitted = False
	data = None
	error = None

	try:
		if not frappe.has_permission(doctype, "read", user=user):
			raise PermissionError(f"You do not have read access to {doctype}.")

		permitted = True
		doc = frappe.get_doc(doctype, name)

		if not frappe.has_permission(doctype, "read", doc=doc, user=user):
			raise PermissionError(f"You do not have access to this {doctype} record.")

		raw = doc.as_dict()
		meta = frappe.get_meta(doctype)
		password_fields = {f.fieldname for f in meta.fields if f.fieldtype == "Password"}

		data = {k: v for k, v in raw.items() if k not in password_fields}

	except PermissionError as exc:
		error = str(exc)
	except frappe.DoesNotExistError:
		error = f"{doctype} '{name}' does not exist or you do not have access."
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "get_document tool error")
		error = f"Error retrieving document: {exc!s}"

	_log_call(
		user=user,
		doctype=doctype,
		was_permitted=permitted,
		execution_ms=int((time.monotonic() - start_ms) * 1000),
	)

	if error:
		return {"error": error, "doctype": doctype, "name": name}

	return {"data": data, "doctype": doctype, "name": name}


def _log_call(user, doctype, was_permitted, execution_ms):
	try:
		doc = frappe.new_doc("AI Tool Call Log")
		doc.user = user
		doc.tool_name = "get_document"
		doc.doctype_accessed = doctype
		doc.was_permitted = 1 if was_permitted else 0
		doc.execution_ms = execution_ms
		doc.timestamp = frappe.utils.now()
		doc.insert(ignore_permissions=True)
	except Exception:
		pass


register_tool("get_document", SCHEMA, execute)
