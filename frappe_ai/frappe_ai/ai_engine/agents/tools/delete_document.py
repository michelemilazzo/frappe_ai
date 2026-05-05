import time

import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "delete_document",
		"description": (
			"Delete a document from a Frappe DocType. "
			"Only use this when the user explicitly asks to delete a specific record. "
			"This action is irreversible — confirm with the user before proceeding."
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
					"description": "The document name/ID to delete",
				},
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
	error = None
	result = None

	try:
		if not frappe.has_permission(doctype, "delete", user=user):
			raise PermissionError(f"You do not have delete permission for {doctype}.")

		permitted = True

		doc = frappe.get_doc(doctype, name)

		if not frappe.has_permission(doctype, "delete", doc=doc, user=user):
			raise PermissionError(f"You do not have delete access to this {doctype} record.")

		frappe.delete_doc(doctype, name, ignore_permissions=False, force=False)
		frappe.db.commit()

		result = {
			"success": True,
			"doctype": doctype,
			"name": name,
			"message": f"Deleted {doctype} '{name}' successfully.",
		}

	except PermissionError as exc:
		error = str(exc)
	except frappe.DoesNotExistError:
		error = f"{doctype} '{name}' does not exist or you do not have access."
	except frappe.LinkExistsError as exc:
		error = f"Cannot delete — this record is linked to other documents: {exc}"
	except frappe.ValidationError as exc:
		error = f"Validation error: {exc}"
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "delete_document tool error")
		error = f"Error deleting {doctype} '{name}': {exc!s}"

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
		doc.tool_name = "delete_document"
		doc.doctype_accessed = doctype
		doc.was_permitted = 1 if was_permitted else 0
		doc.execution_ms = execution_ms
		doc.timestamp = frappe.utils.now()
		doc.insert(ignore_permissions=True)
	except Exception:
		pass


register_tool("delete_document", SCHEMA, execute)
