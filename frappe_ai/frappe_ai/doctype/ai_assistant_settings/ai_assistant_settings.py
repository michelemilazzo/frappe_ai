import frappe
from frappe.exceptions import ValidationError
from frappe.model.document import Document


class AIAssistantSettings(Document):
	def validate(self):
		if self.temperature is not None and not (0.0 <= self.temperature <= 2.0):
			frappe.throw("Temperature must be between 0.0 and 2.0")
		if self.max_tokens is not None and self.max_tokens < 1:
			frappe.throw("Max Tokens must be at least 1")

		if self.provider == "OpenCode":
			self._validate_opencode_model()

	def _validate_opencode_model(self):
		if not self.model:
			return

		api_key = self.get_password("api_key")
		if not api_key:
			return

		try:
			from frappe_ai.frappe_ai.ai_engine.providers.opencode_provider import OpenCodeProvider
			from frappe_ai.frappe_ai.ai_engine.base_provider import (
				ProviderError,
				ProviderRateLimitError,
			)

			provider = OpenCodeProvider(
				{
					"provider": "OpenCode",
					"api_key": api_key,
					"model": self.model,
					"max_tokens": self.max_tokens,
					"temperature": self.temperature,
				}
			)
			supported_models = provider.list_supported_models()
			if (self.model or "").lower() not in {(m or "").lower() for m in (supported_models or [])}:
				models = supported_models or []
				valid_models = ", ".join((models or [])[:8])
				raise ValidationError(
					"Il modello '{0}' non è supportato da questa chiave OpenCode. Prova uno dei seguenti: {1}".format(
						self.model,
						valid_models or "nessun modello disponibile",
					)
				)
		except (ProviderError, ProviderRateLimitError):
			frappe.log_error(frappe.get_traceback(), "OpenCode model validation failed")
			return
		except ValidationError:
			raise
		except Exception:
			frappe.log_error(frappe.get_traceback(), "OpenCode model validation failed")
			return
