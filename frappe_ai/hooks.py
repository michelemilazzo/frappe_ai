app_name = "frappe_ai"
app_title = "Frappe AI — DevOps Assistant"
app_publisher = "Michele Milazzo"
app_description = "AI-powered DevOps assistant for Frappe v16 — powered by OpenCode.ai, Gemini, Groq, Anthropic, or self-hosted LLMs. 18 integrated tools for app management, code analysis, bug monitoring, and automation. Native Espresso UI."
app_email = "michelemilazzo@gmail.com"
app_license = "mit"
app_version = "1.1.0"

app_include_js = "/assets/frappe_ai/js/frappe_ai_chat.js"

after_install = "frappe_ai.frappe_ai.setup.after_install"
before_uninstall = "frappe_ai.frappe_ai.setup.before_uninstall"

permission_query_conditions = {
	"AI Conversation": "frappe_ai.frappe_ai.doctype.ai_conversation.ai_conversation.get_permission_query_conditions",
}

scheduler_events = {
	"daily": [
		"frappe_ai.frappe_ai.ai_engine.rate_limiter.reset_daily_usage",
	],
	"hourly": [
		"frappe_ai.frappe_ai.ai_engine.rate_limiter.clean_expired_records",
	],
}
