import os

import frappe

_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "system_prompt.md")


def _load_prompt_template() -> str:
	with open(_PROMPT_PATH, encoding="utf-8") as f:
		return f.read()


def build_system_prompt(user: str) -> str:
	from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import get_tools_for_llm
	from frappe_ai.frappe_ai.ai_engine.router import get_settings

	settings = get_settings()
	write_enabled = bool(settings.get("allow_write_tools"))
	tool_calling_enabled = bool(settings.get("tool_calling_enabled"))

	# User info
	try:
		user_doc = frappe.get_doc("User", user)
		full_name = user_doc.full_name or user
		roles = [r.role for r in user_doc.roles if r.role]
	except Exception:
		full_name = user
		roles = []

	defaults = frappe.defaults.get_defaults(user)
	company = defaults.get("company", "") or "Not set"
	currency = defaults.get("currency", "") or "USD"

	# ERPNext version (optional)
	erpnext_version_line = ""
	try:
		import erpnext
		erpnext_version_line = f"\n- ERPNext version: {erpnext.__version__}"
	except Exception:
		pass

	# Site name
	try:
		site_name = frappe.local.site or "unknown"
	except Exception:
		site_name = "unknown"

	# Today formatted
	today_raw = frappe.utils.today()  # YYYY-MM-DD
	try:
		from datetime import datetime
		today_date = datetime.strptime(today_raw, "%Y-%m-%d").strftime("%A, %d %B %Y")
	except Exception:
		today_date = today_raw

	# Available tools
	if tool_calling_enabled:
		try:
			tool_schemas = get_tools_for_llm(user)
			available_tools = ", ".join(
				t.get("function", {}).get("name", "") for t in tool_schemas
			) or "none"
		except Exception:
			available_tools = "unavailable"
	else:
		available_tools = "none (tool calling disabled)"

	# Use base prompt from settings if customised, otherwise load from file
	base_prompt = (settings.get("default_system_prompt") or "").strip()
	if not base_prompt:
		base_prompt = _load_prompt_template()

	prompt = base_prompt.replace("{{USER_FULL_NAME}}", full_name)
	prompt = prompt.replace("{{USER_EMAIL}}", user)
	prompt = prompt.replace("{{USER_ROLES}}", ", ".join(roles) or "None")
	prompt = prompt.replace("{{DEFAULT_COMPANY}}", company)
	prompt = prompt.replace("{{DEFAULT_CURRENCY}}", currency)
	prompt = prompt.replace("{{TODAY_DATE}}", today_date)
	prompt = prompt.replace("{{FRAPPE_VERSION}}", frappe.__version__)
	prompt = prompt.replace("{{ERPNEXT_VERSION_LINE}}", erpnext_version_line)
	prompt = prompt.replace("{{SITE_NAME}}", site_name)
	prompt = prompt.replace("{{TOOL_CALLING_ENABLED}}", "yes" if tool_calling_enabled else "no")
	prompt = prompt.replace("{{WRITE_TOOLS_ENABLED}}", "yes" if write_enabled else "no")
	prompt = prompt.replace("{{AVAILABLE_TOOLS}}", available_tools)

	return prompt


def build_context(conversation_id: str, new_message: str, user: str, settings: dict, provider=None) -> list:
	system_prompt = build_system_prompt(user)
	messages = [{"role": "system", "content": system_prompt}]

	try:
		conv_doc = frappe.get_doc("AI Conversation", conversation_id)

		if conv_doc.owner != user and "System Manager" not in frappe.get_roles(user):
			raise PermissionError("Access denied to this conversation.")

		setting_budget = int(settings.get("max_tokens", 8192) * 0.75)
		if provider is not None:
			try:
				# Reserve half the provider's context window for history; the rest
				# covers system prompt + new message + output tokens.
				provider_budget = provider.get_context_window() // 2
				max_context_tokens = min(setting_budget, provider_budget)
			except Exception:
				max_context_tokens = setting_budget
		else:
			max_context_tokens = setting_budget

		all_messages = list(conv_doc.messages or [])
		token_budget = max_context_tokens
		included = []

		for msg in reversed(all_messages):
			if msg.role not in ("user", "assistant", "tool"):
				continue
			content = msg.content or ""
			estimated_tokens = max(1, len(content) // 4)
			if token_budget - estimated_tokens < 0:
				break
			token_budget -= estimated_tokens
			included.append({"role": msg.role, "content": content})

		messages.extend(reversed(included))

	except PermissionError:
		raise
	except frappe.DoesNotExistError:
		pass
	except Exception:
		frappe.log_error(frappe.get_traceback(), "context_manager.build_context error")

	messages.append({"role": "user", "content": new_message})
	return messages
