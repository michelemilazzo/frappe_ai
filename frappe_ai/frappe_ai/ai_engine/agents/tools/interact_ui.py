import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "interact_ui",
		"description": (
			"Interact with any element on the currently visible Frappe desk page. "
			"Covers: form actions (save/submit/cancel/amend/delete), field editing, "
			"child table rows, list-view filters and row selection, report filters, "
			"clicking any button or element by label or CSS selector, typing into inputs, "
			"opening/closing dialogs, expanding sections/tabs, and more. "
			"Always call get_page_context first. "
			"For navigation use navigate_ui instead."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"action": {
					"type": "string",
					"enum": [
						# ── Form document actions ──
						"save_form",
						"submit_document",
						"cancel_document",
						"amend_document",
						"delete_document",
						"new_document",
						# ── Form field actions ──
						"set_field_value",
						"scroll_to_field",
						"expand_section",
						# ── Form child table ──
						"add_child_row",
						"set_child_row_value",
						"delete_child_row",
						# ── Generic click / type ──
						"click_button",
						"click_element",
						"type_in_element",
						# ── List view ──
						"add_list_filter",
						"remove_list_filter",
						"clear_list_filters",
						"click_list_action",
						"select_list_rows",
						# ── Report ──
						"set_report_filter",
						"run_report",
						# ── Dialog ──
						"open_quick_entry",
						"open_dialog_action",
						"close_dialog",
					],
					"description": (
						"save_form — save the open form; "
						"submit_document — submit; "
						"cancel_document — cancel (confirm=true to skip dialog); "
						"amend_document — amend a cancelled doc; "
						"delete_document — delete (confirm=true to skip dialog); "
						"new_document — open a blank new-doc form; "
						"set_field_value — set a field on the open form (fieldname + value); "
						"scroll_to_field — scroll a field into view (fieldname); "
						"expand_section — expand a collapsed section or tab by its label; "
						"add_child_row — add a row to a child table (table_fieldname); "
						"set_child_row_value — set a cell in a child table (table_fieldname, row_index 0-based, fieldname, value); "
						"delete_child_row — delete a child table row (table_fieldname, row_index); "
						"click_button — click a button by its visible label anywhere on the page; "
						"click_element — click any DOM element by CSS selector or partial visible text (selector OR text); "
						"type_in_element — focus an input/textarea by CSS selector or label then type text (selector OR label, text); "
						"add_list_filter — add a filter to the current list view (fieldname, operator, value); "
						"remove_list_filter — remove a specific list filter by fieldname; "
						"clear_list_filters — remove all active list filters; "
						"click_list_action — click a list toolbar button or dropdown item by label; "
						"select_list_rows — select rows in list view (select_all=true, or names=[...]); "
						"set_report_filter — set a filter on the open query/script report (label, value); "
						"run_report — click Run / Refresh on the open report; "
						"open_quick_entry — open quick-entry dialog for a doctype; "
						"open_dialog_action — click a button inside the currently open dialog (button_label); "
						"close_dialog — close the topmost open Frappe dialog."
					),
				},
				# ── shared ──
				"confirm": {
					"type": "boolean",
					"description": "For cancel_document and delete_document: auto-confirm without showing dialog. Only set true after user explicitly approves.",
					"default": False,
				},
				# ── field / form ──
				"fieldname": {
					"type": "string",
					"description": "Field API name (snake_case). Used by set_field_value, scroll_to_field, add_list_filter, remove_list_filter.",
				},
				"value": {
					"description": "New value for set_field_value, set_child_row_value, set_report_filter, add_list_filter, type_in_element.",
				},
				"section_label": {
					"type": "string",
					"description": "For expand_section: visible heading of the section or tab to expand.",
				},
				# ── child table ──
				"table_fieldname": {
					"type": "string",
					"description": "For add_child_row, set_child_row_value, delete_child_row: fieldname of the child table on the parent form.",
				},
				"row_index": {
					"type": "integer",
					"description": "For set_child_row_value, delete_child_row: 0-based row index.",
				},
				# ── button / element ──
				"button_label": {
					"type": "string",
					"description": "For click_button, open_dialog_action: visible text on the button (case-insensitive).",
				},
				"selector": {
					"type": "string",
					"description": "For click_element, type_in_element: CSS selector of the target element.",
				},
				"text": {
					"type": "string",
					"description": "For click_element (partial visible text match) or type_in_element (text to type).",
				},
				"label": {
					"type": "string",
					"description": "For type_in_element: visible label text above/beside the input to target.",
				},
				# ── list ──
				"operator": {
					"type": "string",
					"description": "For add_list_filter: Frappe filter operator. One of: '=', '!=', 'like', 'not like', '>', '<', '>=', '<=', 'in', 'not in', 'between', 'is', 'is not'. Defaults to '='.",
					"enum": ["=", "!=", "like", "not like", ">", "<", ">=", "<=", "in", "not in", "between", "is", "is not"],
				},
				"select_all": {
					"type": "boolean",
					"description": "For select_list_rows: select all visible rows.",
				},
				"names": {
					"type": "array",
					"items": {"type": "string"},
					"description": "For select_list_rows: list of document names to select.",
				},
				"list_action": {
					"type": "string",
					"description": "For click_list_action: toolbar action label (e.g. 'Delete', 'Assign To', 'Export').",
				},
				# ── report ──
				"filter_label": {
					"type": "string",
					"description": "For set_report_filter: the visible label of the report filter field.",
				},
				# ── new / quick entry ──
				"doctype": {
					"type": "string",
					"description": "For new_document, open_quick_entry: target DocType.",
				},
			},
			"required": ["action"],
		},
	},
}

_DESTRUCTIVE = {"delete_document", "cancel_document"}


def execute(args: dict, user: str) -> dict:
	action = (args.get("action") or "").strip()

	valid_actions = {
		"save_form", "submit_document", "cancel_document", "amend_document",
		"delete_document", "new_document",
		"set_field_value", "scroll_to_field", "expand_section",
		"add_child_row", "set_child_row_value", "delete_child_row",
		"click_button", "click_element", "type_in_element",
		"add_list_filter", "remove_list_filter", "clear_list_filters",
		"click_list_action", "select_list_rows",
		"set_report_filter", "run_report",
		"open_quick_entry", "open_dialog_action", "close_dialog",
	}

	if action not in valid_actions:
		return {"error": f"Unknown action '{action}'."}

	payload: dict = {"action": action}

	# ── validation + payload assembly ────────────────────────────────────────
	if action in ("save_form", "submit_document", "amend_document",
	              "clear_list_filters", "run_report", "close_dialog"):
		pass  # no extra params

	elif action in ("cancel_document", "delete_document"):
		payload["confirm"] = bool(args.get("confirm", False))

	elif action == "new_document":
		if args.get("doctype"):
			payload["doctype"] = args["doctype"].strip()

	elif action == "set_field_value":
		fn = (args.get("fieldname") or "").strip()
		if not fn:
			return {"error": "'fieldname' required for set_field_value."}
		payload["fieldname"] = fn
		payload["value"] = args.get("value")

	elif action == "scroll_to_field":
		fn = (args.get("fieldname") or "").strip()
		if not fn:
			return {"error": "'fieldname' required for scroll_to_field."}
		payload["fieldname"] = fn

	elif action == "expand_section":
		lbl = (args.get("section_label") or "").strip()
		if not lbl:
			return {"error": "'section_label' required for expand_section."}
		payload["section_label"] = lbl

	elif action == "add_child_row":
		tf = (args.get("table_fieldname") or "").strip()
		if not tf:
			return {"error": "'table_fieldname' required for add_child_row."}
		payload["table_fieldname"] = tf

	elif action == "set_child_row_value":
		tf = (args.get("table_fieldname") or "").strip()
		fn = (args.get("fieldname") or "").strip()
		if not tf or not fn:
			return {"error": "'table_fieldname' and 'fieldname' required for set_child_row_value."}
		payload["table_fieldname"] = tf
		payload["fieldname"] = fn
		payload["row_index"] = int(args.get("row_index") or 0)
		payload["value"] = args.get("value")

	elif action == "delete_child_row":
		tf = (args.get("table_fieldname") or "").strip()
		if not tf:
			return {"error": "'table_fieldname' required for delete_child_row."}
		payload["table_fieldname"] = tf
		payload["row_index"] = int(args.get("row_index") or 0)

	elif action == "click_button":
		lbl = (args.get("button_label") or "").strip()
		if not lbl:
			return {"error": "'button_label' required for click_button."}
		payload["button_label"] = lbl

	elif action == "click_element":
		sel = (args.get("selector") or "").strip()
		txt = (args.get("text") or "").strip()
		if not sel and not txt:
			return {"error": "'selector' or 'text' required for click_element."}
		if sel:
			payload["selector"] = sel
		if txt:
			payload["text"] = txt

	elif action == "type_in_element":
		sel = (args.get("selector") or "").strip()
		lbl = (args.get("label") or "").strip()
		txt = str(args.get("text") or args.get("value") or "")
		if not sel and not lbl:
			return {"error": "'selector' or 'label' required for type_in_element."}
		if not txt and txt != "0":
			return {"error": "'text' required for type_in_element."}
		if sel:
			payload["selector"] = sel
		if lbl:
			payload["label"] = lbl
		payload["text"] = txt

	elif action == "add_list_filter":
		fn = (args.get("fieldname") or "").strip()
		if not fn:
			return {"error": "'fieldname' required for add_list_filter."}
		payload["fieldname"] = fn
		payload["operator"] = (args.get("operator") or "=").strip()
		payload["value"] = args.get("value", "")

	elif action == "remove_list_filter":
		fn = (args.get("fieldname") or "").strip()
		if not fn:
			return {"error": "'fieldname' required for remove_list_filter."}
		payload["fieldname"] = fn

	elif action == "click_list_action":
		la = (args.get("list_action") or "").strip()
		if not la:
			return {"error": "'list_action' required for click_list_action."}
		payload["list_action"] = la

	elif action == "select_list_rows":
		payload["select_all"] = bool(args.get("select_all", False))
		payload["names"] = list(args.get("names") or [])

	elif action == "set_report_filter":
		fl = (args.get("filter_label") or "").strip()
		if not fl:
			return {"error": "'filter_label' required for set_report_filter."}
		payload["filter_label"] = fl
		payload["value"] = args.get("value", "")

	elif action == "open_quick_entry":
		dt = (args.get("doctype") or "").strip()
		if not dt:
			return {"error": "'doctype' required for open_quick_entry."}
		if not frappe.db.exists("DocType", dt):
			return {"error": f"DocType '{dt}' does not exist."}
		if not frappe.has_permission(dt, "create", user=user):
			return {"error": f"No create permission on '{dt}'."}
		payload["doctype"] = dt

	elif action == "open_dialog_action":
		lbl = (args.get("button_label") or "").strip()
		if not lbl:
			return {"error": "'button_label' required for open_dialog_action."}
		payload["button_label"] = lbl

	return {
		"ui_action": payload,
		"message": f"Performing: {_human_label(action, args)}.",
	}


def _human_label(action, args) -> str:
	m = {
		"save_form": "saving form",
		"submit_document": "submitting document",
		"cancel_document": "cancelling document",
		"amend_document": "amending document",
		"delete_document": "deleting document",
		"clear_list_filters": "clearing list filters",
		"run_report": "running report",
		"close_dialog": "closing dialog",
	}
	if action in m:
		return m[action]
	if action == "new_document":
		return f"new {args.get('doctype', 'document')} form"
	if action == "set_field_value":
		return f"setting {args.get('fieldname')} → {args.get('value')}"
	if action == "scroll_to_field":
		return f"scrolling to {args.get('fieldname')}"
	if action == "expand_section":
		return f"expanding section '{args.get('section_label')}'"
	if action == "add_child_row":
		return f"adding row to {args.get('table_fieldname')}"
	if action == "set_child_row_value":
		return f"setting {args.get('table_fieldname')}[{args.get('row_index',0)}].{args.get('fieldname')}"
	if action == "delete_child_row":
		return f"deleting row {args.get('row_index',0)} from {args.get('table_fieldname')}"
	if action == "click_button":
		return f"clicking '{args.get('button_label')}'"
	if action == "click_element":
		return f"clicking element {args.get('selector') or args.get('text')}"
	if action == "type_in_element":
		return f"typing into {args.get('selector') or args.get('label')}"
	if action == "add_list_filter":
		return f"adding filter {args.get('fieldname')} {args.get('operator','=')} {args.get('value')}"
	if action == "remove_list_filter":
		return f"removing filter on {args.get('fieldname')}"
	if action == "click_list_action":
		return f"list action '{args.get('list_action')}'"
	if action == "select_list_rows":
		return "selecting list rows"
	if action == "set_report_filter":
		return f"report filter '{args.get('filter_label')}' → {args.get('value')}"
	if action == "open_quick_entry":
		return f"quick entry for {args.get('doctype')}"
	if action == "open_dialog_action":
		return f"dialog button '{args.get('button_label')}'"
	return action


register_tool("interact_ui", SCHEMA, execute)
