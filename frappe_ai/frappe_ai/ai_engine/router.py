import frappe

from frappe_ai.frappe_ai.ai_engine.base_provider import ProviderError

PROVIDER_MAP = {
	"Gemini": "frappe_ai.frappe_ai.ai_engine.providers.gemini_provider.GeminiProvider",
	"OpenAI": "frappe_ai.frappe_ai.ai_engine.providers.openai_provider.OpenAIProvider",
	"Anthropic": "frappe_ai.frappe_ai.ai_engine.providers.anthropic_provider.AnthropicProvider",
	"Groq": "frappe_ai.frappe_ai.ai_engine.providers.groq_provider.GroqProvider",
	"Ollama": "frappe_ai.frappe_ai.ai_engine.providers.ollama_provider.OllamaProvider",
	"Grok": "frappe_ai.frappe_ai.ai_engine.providers.grok_provider.GrokProvider",
	"Nvidia": "frappe_ai.frappe_ai.ai_engine.providers.nvidia_provider.NvidiaProvider",
}


def get_settings() -> dict:
	"""Load AI Assistant Settings and return as a plain dict. Never caches api_key in Redis."""
	cache_key = "_frappe_ai_settings"
	cached = getattr(frappe.local, cache_key, None)
	if cached is not None:
		return cached

	doc = frappe.get_single("AI Assistant Settings")
	api_key = frappe.utils.password.get_decrypted_password(
		"AI Assistant Settings", "AI Assistant Settings", "api_key"
	)

	settings = {
		"provider": doc.provider,
		"api_key": api_key or "",
		"api_base_url": doc.api_base_url or "",
		"model": doc.model or "gemini-2.0-flash",
		"max_tokens": doc.max_tokens or 8192,
		"temperature": doc.temperature if doc.temperature is not None else 0.7,
		"streaming_enabled": bool(doc.streaming_enabled),
		"tool_calling_enabled": bool(doc.tool_calling_enabled),
		"allow_write_tools": bool(doc.allow_write_tools),
		"file_upload_enabled": bool(doc.file_upload_enabled),
		"allowed_file_types": doc.allowed_file_types or ".pdf,.png,.jpg,.jpeg,.xlsx,.csv",
		"max_file_size_mb": doc.max_file_size_mb or 10,
		"rate_limit_per_user": doc.rate_limit_per_user or 60,
		"monthly_budget_usd": doc.monthly_budget_usd or 0,
		"audit_log_retention_days": doc.audit_log_retention_days or 90,
		"default_system_prompt": doc.default_system_prompt or "",
	}

	setattr(frappe.local, cache_key, settings)
	return settings


def get_provider(settings: dict = None):
	"""Instantiate and return the configured provider."""
	if settings is None:
		settings = get_settings()

	provider_name = settings.get("provider", "Gemini")
	cls_path = PROVIDER_MAP.get(provider_name)

	if not cls_path:
		raise ProviderError(f"Unknown provider: {provider_name}")

	if not settings.get("api_key"):
		raise ProviderError("API key is not configured. Please set it in AI Assistant Settings.")

	try:
		cls = frappe.get_attr(cls_path)
	except Exception as exc:
		raise ProviderError(f"Provider {provider_name} is not installed or available.") from exc

	return cls(settings)
