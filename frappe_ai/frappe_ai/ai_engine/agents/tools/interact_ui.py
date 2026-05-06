import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

SCHEMA = {
	"type": "function",
	"function": {
		"name": "interact_ui",
		"description": (
			"Interact with elements on the currently visible Frappe desk page. "
			"Use this to click buttons (Save, Delete, Submit, Cancel, Amend, New, etc.), "
			"set field values on the open form, click list-view row action buttons, "
			"open quick entry dialogs, trigger toolbar actions, or scroll to a field. "
			"Always call get_page_context first so you know what is on screen. "
			"Do NOT use this for navigation — use navigate_ui instead."
		),
		"parameters": {
			"type": "object",
			"properties": {
				"action": {
					"type": "string",
					"enum": [
						"click_button",
						"set_field_value",
						"save_form",
						"delete_document",
						"submit_document",
						"cancel_document",
						"amend_document",
						"new_document",
						"click_list_action",
						"open_quick_entry",
						"scroll_to_field",
						"trigger_form_action",
					],
					"description": (
						"The interaction to perform:\n"
						"'click_button' — click any named button on the current page (e.g. 'Save', 'Delete', 'Add Row', 'Submit');\n"
						"'set_field_value' — set a field value on the currently open form;\n"
						"'save_form' — save the currently open form (equivalent to clicking Save);\n"
						"'delete_document' — delete the currently open document (shows confirmation);\n"
						"'submit_document' — submit the currently open document;\n"
						"'cancel_document' — cancel the currently open document;\n"
						"'amend_document' — amend the currently open cancelled document;\n"
						"'new_document' — click the New button to open a new form for the current doctype;\n"
						"'click_list_action' — click a list-toolbar action button (e.g. 'Delete', 'Assign To', 'Export');\n"
						"'open_quick_entry' — open the quick entry dialog for a doctype;\n"
						"'scroll_to_field' — scroll the form to bring a specific field into view;\n"
						"'trigger_form_action' — trigger a named custom form button/action."
					),
				},
				"button_label": {
					"type": "string",
					"description": "For 'click_button' and 'trigger_form_action': the visible label of the button to click (case-insensitive). E.g. 'Save', 'Add Row', 'Get Items'.",
				},
				"fieldname": {
					"type": "string",
					"description": "For 'set_field_value' and 'scroll_to_field': the fieldname of the target field.",
				},
				"value": {
					"description": "For 'set_field_value': the new value to set. Use string for text/select, number for Int/Float, boolean for Check.",
				},
				"doctype": {
					"type": "string",
					"description": "For 'open_quick_entry' and 'new_document': the DocType to use.",
				},
				"list_action": {
					"type": "string",
					"description": "For 'click_list_action': the toolbar action label (e.g. 'Delete', 'Assign To', 'Export', 'Set Field').",
				},
				"confirm": {
					"type": "boolean",
					"description": "For destructive actions ('delete_document', 'cancel_document'): whether to auto-confirm the dialog. Defaults to false — the AI should always ask the user before setting this to true.",
					"default": False,
				},
			},
			"required": ["action"],
		},
	},
}

# Actions the AI must get explicit user confirmation before executing
_DESTRUCTIVE_ACTIONS = {"delete_document", "cancel_document"}


def execute(args: dict, user: str) -> dict:
	action = (args.get("action") or "").strip()

	valid_actions = {
		"click_button", "set_field_value", "save_form", "delete_document",
		"submit_document", "cancel_document", "amend_document", "new_document",
		"click_list_action", "open_quick_entry", "scroll_to_field", "trigger_form_action",
	}

	if action not in valid_actions:
		return {"error": f"Unknown action '{action}'."}

	# Build the ui_interact payload the client will execute
	payload: dict = {"action": action}

	if action == "click_button":
		label = (args.get("button_label") or "").strip()
		if not label:
			return {"error": "'button_label' is required for 'click_button'."}
		payload["button_label"] = label

	elif action == "set_field_value":
		fieldname = (args.get("fieldname") or "").strip()
		if not fieldname:
			return {"error": "'fieldname' is required for 'set_field_value'."}
		payload["fieldname"] = fieldname
		payload["value"] = args.get("value")

	elif action in ("save_form", "submit_document", "amend_document"):
		pass  # no extra params needed

	elif action in ("delete_document", "cancel_document"):
		payload["confirm"] = bool(args.get("confirm", False))

	elif action == "new_document":
		doctype = (args.get("doctype") or "").strip()
		if doctype:
			payload["doctype"] = doctype

	elif action == "click_list_action":
		list_action = (args.get("list_action") or "").strip()
		if not list_action:
			return {"error": "'list_action' is required for 'click_list_action'."}
		payload["list_action"] = list_action

	elif action == "open_quick_entry":
		doctype = (args.get("doctype") or "").strip()
		if not doctype:
			return {"error": "'doctype' is required for 'open_quick_entry'."}
		if not frappe.db.exists("DocType", doctype):
			return {"error": f"DocType '{doctype}' does not exist."}
		if not frappe.has_permission(doctype, "create", user=user):
			return {"error": f"You do not have create permission for '{doctype}'."}
		payload["doctype"] = doctype

	elif action == "scroll_to_field":
		fieldname = (args.get("fieldname") or "").strip()
		if not fieldname:
			return {"error": "'fieldname' is required for 'scroll_to_field'."}
		payload["fieldname"] = fieldname

	elif action == "trigger_form_action":
		label = (args.get("button_label") or "").strip()
		if not label:
			return {"error": "'button_label' is required for 'trigger_form_action'."}
		payload["button_label"] = label

	label = _human_label(action, args)
	return {
		"ui_action": payload,
		"message": f"Performing: {label}.",
	}


def _human_label(action, args) -> str:
	if action == "click_button":
		return f"clicking '{args.get('button_label', '')}' button"
	if action == "set_field_value":
		return f"setting '{args.get('fieldname', '')}' to '{args.get('value', '')}'"
	if action == "save_form":
		return "saving the form"
	if action == "delete_document":
		return "deleting the document"
	if action == "submit_document":
		return "submitting the document"
	if action == "cancel_document":
		return "cancelling the document"
	if action == "amend_document":
		return "amending the document"
	if action == "new_document":
		return f"opening new {args.get('doctype', 'document')} form"
	if action == "click_list_action":
		return f"clicking list action '{args.get('list_action', '')}'"
	if action == "open_quick_entry":
		return f"opening quick entry for {args.get('doctype', '')}"
	if action == "scroll_to_field":
		return f"scrolling to field '{args.get('fieldname', '')}'"
	if action == "trigger_form_action":
		return f"triggering '{args.get('button_label', '')}'"
	return action


register_tool("interact_ui", SCHEMA, execute)
