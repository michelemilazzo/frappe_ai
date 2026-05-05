app_name = "frappe_ai"
app_title = "Frappe AI"
app_publisher = "Karan Mistry"
app_description = "A plug-and-play AI chat assistant for Frappe v16 — powered by OpenAI, Anthropic, Gemini, Groq, or self-hosted LLMs. Conversational database access scoped strictly to the logged-in user's permissions. Native Espresso UI. Zero config to start."
app_email = "ksmistry007@gmail.com"
app_license = "mit"
app_version = "1.0.0"

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
