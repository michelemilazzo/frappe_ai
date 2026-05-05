_REGISTRY: dict = {}


def register_tool(name: str, schema: dict, handler):
	_REGISTRY[name] = {"schema": schema, "handler": handler}


def get_tools_for_llm(user: str = None) -> list:
	"""Return tool schemas in OpenAI function-calling format."""
	_ensure_tools_loaded()
	return [entry["schema"] for entry in _REGISTRY.values()]


def get_handler(name: str):
	_ensure_tools_loaded()
	entry = _REGISTRY.get(name)
	if not entry:
		raise KeyError(f"No tool registered with name: {name}")
	return entry["handler"]


def _ensure_tools_loaded():
	"""Import all tool modules so their register_tool() calls run."""
	if _REGISTRY:
		return
	import importlib

	tool_modules = [
		"frappe_ai.frappe_ai.ai_engine.agents.tools.search_documents",
		"frappe_ai.frappe_ai.ai_engine.agents.tools.get_document",
		"frappe_ai.frappe_ai.ai_engine.agents.tools.count_documents",
		"frappe_ai.frappe_ai.ai_engine.agents.tools.get_user_context",
		"frappe_ai.frappe_ai.ai_engine.agents.tools.list_doctypes",
		"frappe_ai.frappe_ai.ai_engine.agents.tools.get_doctype_meta",
	]
	for mod_path in tool_modules:
		importlib.import_module(mod_path)
