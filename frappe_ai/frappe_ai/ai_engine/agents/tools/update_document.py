import time

import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "update_document",
		"description": (
			"Update fields on an existing Frappe document. "
			"Only updates the fields you specify — other fields are left unchanged. "
			"Returns the updated document name and a link to view it."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"doctype": {
					"type": "string",
					"description": "The DocType name (e.g. 'Item', 'Customer')",
				},
				"name": {
					"type": "string",
					"description": "The document name/ID to update",
				},
				"values": {
					"type": "object",
					"description": "Field values to update, e.g. {\"status\": \"Closed\", \"description\": \"Updated desc\"}",
				},
			},
			"required": ["doctype", "name", "values"],
		},
	},
}


def execute(args: dict, user: str) -> dict:
	start_ms = time.monotonic()
	doctype = args.get("doctype", "")
	name = args.get("name", "")
	values = args.get("values") or {}
	permitted = False
	error = None
	result = None

	try:
		if not frappe.has_permission(doctype, "write", user=user):
			raise PermissionError(f"You do not have write permission for {doctype}.")

		permitted = True

		doc = frappe.get_doc(doctype, name)

		if not frappe.has_permission(doctype, "write", doc=doc, user=user):
			raise PermissionError(f"You do not have write access to this {doctype} record.")

		# Strip password fields
		meta = frappe.get_meta(doctype)
		password_fields = {f.fieldname for f in meta.fields if f.fieldtype == "Password"}
		safe_values = {k: v for k, v in values.items() if k not in password_fields}

		doc.update(safe_values)
		doc.save(ignore_permissions=False)
		frappe.db.commit()

		doc_url = f"/app/{doctype.lower().replace(' ', '-')}/{doc.name}"
		result = {
			"success": True,
			"doctype": doctype,
			"name": doc.name,
			"url": doc_url,
			"message": f"Updated {doctype} '{doc.name}' successfully.",
			"updated_fields": list(safe_values.keys()),
		}

	except PermissionError as exc:
		error = str(exc)
	except frappe.DoesNotExistError:
		error = f"{doctype} '{name}' does not exist or you do not have access."
	except frappe.ValidationError as exc:
		error = f"Validation error: {exc}"
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "update_document tool error")
		error = f"Error updating {doctype} '{name}': {exc!s}"

	_log_call(
		user=user,
		doctype=doctype,
		was_permitted=permitted,
		execution_ms=int((time.monotonic() - start_ms) * 1000),
	)

	if error:
		return {"error": error, "doctype": doctype, "name": name}

	return result


def _log_call(user, doctype, was_permitted, execution_ms):
	try:
		doc = frappe.new_doc("AI Tool Call Log")
		doc.user = user
		doc.tool_name = "update_document"
		doc.doctype_accessed = doctype
		doc.was_permitted = 1 if was_permitted else 0
		doc.execution_ms = execution_ms
		doc.timestamp = frappe.utils.now()
		doc.insert(ignore_permissions=True)
	except Exception:
		pass


register_tool("update_document", SCHEMA, execute)
