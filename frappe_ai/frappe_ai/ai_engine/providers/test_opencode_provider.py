"""Test coverage for OpenCode provider."""
import unittest
from unittest.mock import MagicMock, patch


class TestOpenCodeProvider(unittest.IsolatedAsyncioTestCase):
	"""Unit tests for the OpenCode provider."""

	def setUp(self):
		self.mock_settings = {
			"api_key": "test-key-123",
			"model": "glm-4.7-free",
			"max_tokens": 4096,
			"temperature": 0.7,
			"streaming_enabled": True,
		}

	def test_provider_can_be_imported(self):
		"""The OpenCodeProvider class must be importable."""
		from frappe_ai.frappe_ai.ai_engine.providers.opencode_provider import (
			OpenCodeProvider,
			_get_api_type,
			_get_endpoint_url,
		)

		self.assertTrue(callable(OpenCodeProvider))

	def test_get_api_type_routing(self):
		"""Model name prefix correctly determines API type."""
		from frappe_ai.frappe_ai.ai_engine.providers.opencode_provider import (
			_get_api_type,
		)

		self.assertEqual(_get_api_type("gpt-5.2"), "responses")
		self.assertEqual(_get_api_type("o3-mini"), "responses")
		self.assertEqual(_get_api_type("claude-sonnet-4-5"), "messages")
		self.assertEqual(_get_api_type("gemini-3-flash"), "gemini")
		self.assertEqual(_get_api_type("glm-4.7-free"), "chat_completions")
		self.assertEqual(_get_api_type("kimi-k2"), "chat_completions")
		self.assertEqual(_get_api_type("grok-code-fast-1"), "chat_completions")

	def test_endpoint_urls(self):
		"""Correct endpoint URL for each API type."""
		from frappe_ai.frappe_ai.ai_engine.providers.opencode_provider import (
			_get_endpoint_url,
		)

		self.assertEqual(
			_get_endpoint_url("gpt-5.2", "responses"),
			"https://opencode.ai/zen/v1/responses",
		)
		self.assertEqual(
			_get_endpoint_url("claude-sonnet-4-5", "messages"),
			"https://opencode.ai/zen/v1/messages",
		)
		self.assertEqual(
			_get_endpoint_url("gemini-3-flash", "gemini"),
			"https://opencode.ai/zen/v1/models/gemini-3-flash",
		)
		self.assertEqual(
			_get_endpoint_url("glm-4.7-free", "chat_completions"),
			"https://opencode.ai/zen/v1/chat/completions",
		)

	def test_provider_instantiation(self):
		"""Provider creates instance with correct attributes."""
		from frappe_ai.frappe_ai.ai_engine.providers.opencode_provider import (
			OpenCodeProvider,
		)

		provider = OpenCodeProvider(self.mock_settings)
		self.assertEqual(provider.api_key, "test-key-123")
		self.assertEqual(provider.model, "glm-4.7-free")
		self.assertEqual(provider.max_tokens, 4096)
		self.assertEqual(provider.temperature, 0.7)

	def test_supports_capabilities(self):
		"""Provider reports correct capabilities."""
		from frappe_ai.frappe_ai.ai_engine.providers.opencode_provider import (
			OpenCodeProvider,
		)

		provider = OpenCodeProvider(self.mock_settings)
		self.assertTrue(provider.supports_tools())
		self.assertTrue(provider.supports_vision())

	def test_context_window(self):
		"""Known context window sizes."""
		from frappe_ai.frappe_ai.ai_engine.providers.opencode_provider import (
			OpenCodeProvider,
		)

		p1 = OpenCodeProvider({**self.mock_settings, "model": "gpt-5.2"})
		self.assertEqual(p1.get_context_window(), 200_000)

		p2 = OpenCodeProvider({**self.mock_settings, "model": "gemini-3-pro"})
		self.assertEqual(p2.get_context_window(), 1_000_000)

		p3 = OpenCodeProvider({**self.mock_settings, "model": "unknown-model"})
		self.assertEqual(p3.get_context_window(), 128_000)

	def test_token_counting(self):
		"""Approximate token count is reasonable."""
		from frappe_ai.frappe_ai.ai_engine.providers.opencode_provider import (
			OpenCodeProvider,
		)

		provider = OpenCodeProvider(self.mock_settings)
		messages = [
			{"role": "user", "content": "Hello, how are you?"},
			{"role": "assistant", "content": "I'm doing well, thank you!"},
		]
		count = provider.count_tokens(messages)
		self.assertGreater(count, 0)
		# Rough sanity: ~10 words ≈ ~13 tokens (chars/4)
		self.assertLess(count, 50)

	def test_router_registers_opencode(self):
		"""OpenCode is registered in the PROVIDER_MAP."""
		from frappe_ai.frappe_ai.ai_engine.router import PROVIDER_MAP

		self.assertIn("OpenCode", PROVIDER_MAP)
		self.assertIn("opencode_provider", PROVIDER_MAP["OpenCode"])
		self.assertIn("OpenCodeProvider", PROVIDER_MAP["OpenCode"])


class TestOpenCodeSyncChat(unittest.TestCase):
	"""Test synchronous chat response parsing."""

	def setUp(self):
		from frappe_ai.frappe_ai.ai_engine.providers.opencode_provider import (
			OpenCodeProvider,
		)

		mock_settings = {
			"api_key": "test-key",
			"model": "glm-4.7-free",
			"max_tokens": 4096,
			"temperature": 0.7,
		}
		self.provider = OpenCodeProvider(mock_settings)

	def test_parse_glm_response(self):
		"""Chat Completions format (GLM model) parses correctly."""
		raw = {
			"model": "glm-4.7-free",
			"choices": [
				{
					"message": {
						"role": "assistant",
						"content": "Ciao! Come posso aiutarti?",
					},
					"finish_reason": "stop",
				}
			],
			"usage": {"prompt_tokens": 10, "completion_tokens": 8},
		}

		result = self.provider._parse_response(raw)

		self.assertEqual(result["content"], "Ciao! Come posso aiutarti?")
		self.assertEqual(result["role"], "assistant")
		self.assertIsNone(result["tool_calls"])
		self.assertEqual(result["finish_reason"], "stop")
		self.assertEqual(result["usage"]["input_tokens"], 10)
		self.assertEqual(result["usage"]["output_tokens"], 8)


if __name__ == "__main__":
	unittest.main()