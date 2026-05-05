import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "get_doctype_meta",
		"description": "Get field definitions and metadata for a DocType.",
		"parameters": {
			"type": "object",
			"properties": {
				"doctype": {"type": "string", "description": "The DocType name"},
			},
			"required": ["doctype"],
		},
	},
}


def execute(args: dict, user: str) -> dict:
	doctype = args.get("doctype", "")

	try:
		if not frappe.has_permission(doctype, "read", user=user):
			return {"error": f"You do not have read access to {doctype}."}

		meta = frappe.get_meta(doctype)

		fields = []
		for f in meta.fields:
			if f.fieldtype == "Password":
				continue
			fields.append(
				{
					"fieldname": f.fieldname,
					"label": f.label,
					"fieldtype": f.fieldtype,
					"options": f.options,
				}
			)

		return {
			"meta": {
				"name": meta.name,
				"label": meta.name,
				"description": getattr(meta, "description", ""),
				"title_field": meta.title_field or "name",
				"name_case": getattr(meta, "name_case", ""),
				"fields": fields,
			}
		}
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), "get_doctype_meta tool error")
		return {"error": f"Could not get meta for {doctype}: {exc!s}"}


register_tool("get_doctype_meta", SCHEMA, execute)
