import json

import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import register_tool

_CONTEXT_CACHE_TTL = 30  # seconds

SCHEMA = {
	"type": "function",
	"function": {
		"name": "get_page_context",
		"description": (
			"Get information about the page the user is currently viewing in Frappe desk. "
			"Returns the current route, page type (form/list/report/workspace), doctype, "
			"document name, docstatus, form field values, and list view state. "
			"Call this before using interact_ui so you know what is on screen. "
			"Do NOT call this for data queries — use search_documents or get_document instead."
		),
		"parameters": {
			"type": "object",
			"properties": {},
			"required": [],
		},
	},
}


def execute(args: dict, user: str) -> dict:
	"""Read page context that the client pushed to cache before sending the message."""
	cache_key = f"frappe_ai_page_ctx_{user}"
	try:
		raw = frappe.cache().get_value(cache_key)
		if raw:
			if isinstance(raw, (bytes, str)):
				ctx = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
			else:
				ctx = raw
			return {"page_context": ctx}
	except Exception:
		pass
	return {
		"page_context": {
			"available": False,
			"note": "No page context available. The user may not have the Frappe desk open.",
		}
	}


register_tool("get_page_context", SCHEMA, execute)
