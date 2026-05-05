import json

import frappe

from frappe_ai.frappe_ai.ai_engine.base_provider import (
	BaseProvider,
	ProviderAuthError,
	ProviderError,
	ProviderRateLimitError,
)

_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


def _get_client(api_key: str, base_url: str = ""):
	from openai import OpenAI

	return OpenAI(api_key=api_key, base_url=base_url or _NVIDIA_BASE_URL)


def _wrap_nvidia_error(exc):
	try:
		from openai import APIStatusError, AuthenticationError, RateLimitError

		if isinstance(exc, RateLimitError):
			retry_after = None
			try:
				retry_after = int(exc.response.headers.get("retry-after", 0)) or None
			except Exception:
				pass
			raise ProviderRateLimitError("NVIDIA API quota exceeded. Please wait and try again.", retry_after=retry_after) from exc

		if isinstance(exc, AuthenticationError):
			raise ProviderAuthError("NVIDIA API key is invalid. Please check AI Assistant Settings.") from exc

		if isinstance(exc, APIStatusError):
			status = exc.status_code
			frappe.log_error(frappe.get_traceback(), f"NvidiaProvider API error ({status})")
			raise ProviderError(f"NVIDIA API error {status}: {exc.message}") from exc

	except ImportError:
		pass

	frappe.log_error(frappe.get_traceback(), f"NvidiaProvider unexpected error: {type(exc).__name__}")
	raise ProviderError(str(exc)) from exc


def _build_messages(messages: list) -> list:
	"""Convert to plain user/assistant/system messages — no tool roles."""
	result = []
	for msg in messages:
		role = msg.get("role", "user")
		content = msg.get("content", "") or ""

		# Skip tool result messages — NVIDIA Llama doesn't use tool calling
		if role == "tool":
			continue

		# Strip tool_calls from assistant messages
		if role == "assistant":
			result.append({"role": "assistant", "content": content})
			continue

		result.append({"role": role, "content": content})

	return result


class NvidiaProvider(BaseProvider):
	def chat(self, messages: list, tools: list = None) -> dict:
		try:
			client = _get_client(self.api_key, self.api_base_url)
			oai_messages = _build_messages(messages)

			response = client.chat.completions.create(
				model=self.model,
				messages=oai_messages,
				max_tokens=self.max_tokens,
				temperature=self.temperature,
				top_p=1.0,
			)

			choice = response.choices[0] if response.choices else None
			msg = choice.message if choice else None
			content = (msg.content or "") if msg else ""
			finish_reason = (choice.finish_reason if choice else None) or "stop"

			usage = response.usage
			return {
				"content": content,
				"role": "assistant",
				"tool_calls": None,
				"finish_reason": finish_reason,
				"usage": {
					"input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
					"output_tokens": getattr(usage, "completion_tokens", 0) or 0,
				},
			}

		except (ProviderRateLimitError, ProviderAuthError, ProviderError):
			raise
		except Exception as exc:
			_wrap_nvidia_error(exc)

	def stream(self, messages: list, tools: list = None):
		try:
			client = _get_client(self.api_key, self.api_base_url)
			oai_messages = _build_messages(messages)

			total_input = 0
			total_output = 0
			finish_reason = "stop"

			for chunk in client.chat.completions.create(
				model=self.model,
				messages=oai_messages,
				max_tokens=self.max_tokens,
				temperature=self.temperature,
				top_p=1.0,
				stream=True,
				stream_options={"include_usage": True},
			):
				choice = chunk.choices[0] if chunk.choices else None
				delta = choice.delta if choice else None

				if delta and delta.content:
					yield {"event": "token", "data": {"delta": delta.content}}

				if choice and choice.finish_reason:
					finish_reason = choice.finish_reason

				if chunk.usage:
					total_input = chunk.usage.prompt_tokens or 0
					total_output = chunk.usage.completion_tokens or 0

			yield {
				"event": "done",
				"data": {
					"finish_reason": finish_reason or "stop",
					"usage": {"input": total_input, "output": total_output},
					"tool_calls": None,
				},
			}

		except (ProviderRateLimitError, ProviderAuthError, ProviderError):
			raise
		except Exception as exc:
			try:
				_wrap_nvidia_error(exc)
			except ProviderError as pe:
				yield {"event": "error", "data": {"code": type(pe).__name__, "message": str(pe)}}

	def count_tokens(self, messages: list) -> int:
		total_chars = sum(len(str(m.get("content", ""))) for m in messages)
		return max(1, total_chars // 4)

	def supports_tools(self) -> bool:
		# NVIDIA NIM Llama models echo tool schemas as plain text rather than
		# using the tool_calls field — keep tools disabled to avoid garbled output.
		return False

	def supports_vision(self) -> bool:
		return False

	def get_context_window(self) -> int:
		return 128_000
