import time

import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "create_document",
		"description": (
			"Create a new document in any Frappe DocType the user has create permission for. "
			"Use get_doctype_meta first to discover required fields. "
			"Returns the new document's name and a link to view it."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"doctype": {
					"type": "string",
					"description": "The DocType name (e.g. 'Item', 'Customer', 'Sales Order')",
				},
				"values": {
					"type": "object",
					"description": "Field values to set on the new document, e.g. {\"item_name\": \"Test Item\", \"item_group\": \"All Item Groups\"}",
				},
			},
			"required": ["doctype", "values"],
		},
	},
}


def execute(args: dict, user: str) -> dict:
	start_ms = time.monotonic()
	doctype = args.get("doctype", "")
	values = args.get("values") or {}
	permitted = False
	error = None
	result = None

	try:
		if not frappe.has_permission(doctype, "create", user=user):
			raise PermissionError(f"You do not have create permission for {doctype}.")

		permitted = True

		# Strip any password fields from values
		meta = frappe.get_meta(doctype)
		password_fields = {f.fieldname for f in meta.fields if f.fieldtype == "Password"}
		safe_values = {k: v for k, v in values.items() if k not in password_fields}

		doc = frappe.new_doc(doctype)
		doc.update(safe_values)

		doc.insert(ignore_permissions=False)
		frappe.db.commit()

		doc_url = f"/app/{doctype.lower().replace(' ', '-')}/{doc.name}"
		result = {
			"success": True,
			"doctype": doctype,
			"name": doc.name,
			"url": doc_url,
			"message": f"Created {doctype} '{doc.name}' successfully.",
		}

	except PermissionError as exc:
		error = str(exc)
	except frappe.MandatoryError as exc:
		error = f"Missing required fields: {exc}"
	except frappe.ValidationError as exc:
		error = f"Validation error: {exc}"
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "create_document tool error")
		error = f"Error creating {doctype}: {exc!s}"

	_log_call(
		user=user,
		doctype=doctype,
		was_permitted=permitted,
		execution_ms=int((time.monotonic() - start_ms) * 1000),
	)

	if error:
		return {"error": error, "doctype": doctype}

	return result


def _log_call(user, doctype, was_permitted, execution_ms):
	try:
		doc = frappe.new_doc("AI Tool Call Log")
		doc.user = user
		doc.tool_name = "create_document"
		doc.doctype_accessed = doctype
		doc.was_permitted = 1 if was_permitted else 0
		doc.execution_ms = execution_ms
		doc.timestamp = frappe.utils.now()
		doc.insert(ignore_permissions=True)
	except Exception:
		pass


register_tool("create_document", SCHEMA, execute)
