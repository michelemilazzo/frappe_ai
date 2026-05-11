import frappe

import unittest

from unittest.mock import patch

from frappe_ai.frappe_ai.doctype.ai_assistant_settings.ai_assistant_settings import AIAssistantSettings


class TestAIAssistantSettings(unittest.TestCase):
	"""Unit tests for OpenCode model validation logic."""

	def _build_doc(self):
		doc = AIAssistantSettings.__new__(AIAssistantSettings)
		doc.provider = "OpenCode"
		doc.model = "glm-5"
		doc.max_tokens = 1024
		doc.temperature = 0.7
		doc.get_password = lambda fieldname="api_key": "test-key"
		return doc

	def _assert_raises_validation_error(self, fn):
		with self.assertRaises(frappe.ValidationError):
			fn()

	def test_opencode_model_validation_accepts_supported_model(self):
		doc = self._build_doc()

		class DummyProvider:
			def __init__(self, settings):
				self.settings = settings

			def list_supported_models(self):
				return ["glm-5", "qwen3.6-plus", "kimi-k2.6"]

		with patch(
			"frappe_ai.frappe_ai.ai_engine.providers.opencode_provider.OpenCodeProvider",
			DummyProvider,
		):
			doc._validate_opencode_model()

	def test_opencode_model_validation_rejects_unsupported_model(self):
		doc = self._build_doc()
		doc.model = "definitely-not-supported"

		class DummyProvider:
			def __init__(self, settings):
				self.settings = settings

			def list_supported_models(self):
				return ["glm-5", "qwen3.6-plus"]

		with patch(
			"frappe_ai.frappe_ai.ai_engine.providers.opencode_provider.OpenCodeProvider",
			DummyProvider,
		):
			self._assert_raises_validation_error(doc._validate_opencode_model)

	def test_opencode_model_validation_nonblocking_on_provider_error(self):
		doc = self._build_doc()
		doc.model = "whatever"

		class DummyProvider:
			def __init__(self, settings):
				self.settings = settings

			def list_supported_models(self):
				raise RuntimeError("network down")

		with patch(
			"frappe_ai.frappe_ai.ai_engine.providers.opencode_provider.OpenCodeProvider",
			DummyProvider,
		):
			doc._validate_opencode_model()
