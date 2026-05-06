_REGISTRY: dict = {}

_READ_TOOL_MODULES = [
	"frappe_ai.frappe_ai.ai_engine.agents.tools.search_documents",
	"frappe_ai.frappe_ai.ai_engine.agents.tools.get_document",
	"frappe_ai.frappe_ai.ai_engine.agents.tools.count_documents",
	"frappe_ai.frappe_ai.ai_engine.agents.tools.get_user_context",
	"frappe_ai.frappe_ai.ai_engine.agents.tools.list_doctypes",
	"frappe_ai.frappe_ai.ai_engine.agents.tools.get_doctype_meta",
	"frappe_ai.frappe_ai.ai_engine.agents.tools.navigate_ui",
	"frappe_ai.frappe_ai.ai_engine.agents.tools.get_page_context",
	"frappe_ai.frappe_ai.ai_engine.agents.tools.interact_ui",
]

_WRITE_TOOL_MODULES = [
	"frappe_ai.frappe_ai.ai_engine.agents.tools.create_document",
	"frappe_ai.frappe_ai.ai_engine.agents.tools.update_document",
	"frappe_ai.frappe_ai.ai_engine.agents.tools.delete_document",
]

_WRITE_TOOL_NAMES = {"create_document", "update_document", "delete_document"}

_loaded_read = False
_loaded_write = False


def register_tool(name: str, schema: dict, handler):
	_REGISTRY[name] = {"schema": schema, "handler": handler}


def get_tools_for_llm(user: str = None) -> list:
	"""Return tool schemas respecting the allow_write_tools setting."""
	_ensure_read_tools_loaded()

	write_enabled = _write_tools_allowed()
	if write_enabled:
		_ensure_write_tools_loaded()

	return [
		entry["schema"]
		for name, entry in _REGISTRY.items()
		if name not in _WRITE_TOOL_NAMES or write_enabled
	]


def get_handler(name: str):
	_ensure_read_tools_loaded()
	_ensure_write_tools_loaded()
	entry = _REGISTRY.get(name)
	if not entry:
		raise KeyError(f"No tool registered with name: {name}")
	return entry["handler"]


def _write_tools_allowed() -> bool:
	try:
		import frappe
		return bool(frappe.db.get_single_value("AI Assistant Settings", "allow_write_tools"))
	except Exception:
		return False


def _ensure_read_tools_loaded():
	global _loaded_read
	if _loaded_read:
		return
	import importlib
	for mod_path in _READ_TOOL_MODULES:
		importlib.import_module(mod_path)
	_loaded_read = True


def _ensure_write_tools_loaded():
	global _loaded_write
	if _loaded_write:
		return
	import importlib
	for mod_path in _WRITE_TOOL_MODULES:
		importlib.import_module(mod_path)
	_loaded_write = True
