import json

import frappe

from frappe_ai.frappe_ai.ai_engine.base_provider import (
	BaseProvider,
	ProviderAuthError,
	ProviderError,
	ProviderRateLimitError,
)

_GROK_BASE_URL = "https://api.x.ai/v1"


def _get_client(api_key: str, base_url: str = ""):
	from openai import OpenAI

	return OpenAI(api_key=api_key, base_url=base_url or _GROK_BASE_URL)


def _wrap_openai_error(exc):
	try:
		from openai import APIStatusError, AuthenticationError, RateLimitError

		if isinstance(exc, RateLimitError):
			retry_after = None
			try:
				retry_after = int(exc.response.headers.get("retry-after", 0)) or None
			except Exception:
				pass
			raise ProviderRateLimitError("Grok API quota exceeded. Please wait and try again.", retry_after=retry_after) from exc

		if isinstance(exc, AuthenticationError):
			raise ProviderAuthError("Grok API key is invalid. Please check AI Assistant Settings.") from exc

		if isinstance(exc, APIStatusError):
			status = exc.status_code
			frappe.log_error(frappe.get_traceback(), f"GrokProvider API error ({status})")
			raise ProviderError(f"Grok API error {status}: {exc.message}") from exc

	except ImportError:
		pass

	frappe.log_error(frappe.get_traceback(), f"GrokProvider unexpected error: {type(exc).__name__}")
	raise ProviderError(str(exc)) from exc


def _build_messages(messages: list) -> list:
	"""Pass OpenAI-style messages straight through — xAI API is OpenAI-compatible."""
	result = []
	for msg in messages:
		role = msg.get("role", "user")
		content = msg.get("content", "") or ""

		if role == "tool":
			result.append({
				"role": "tool",
				"tool_call_id": msg.get("tool_call_id", ""),
				"content": content,
			})
		elif role == "assistant" and msg.get("tool_calls"):
			result.append({
				"role": "assistant",
				"content": content,
				"tool_calls": msg["tool_calls"],
			})
		else:
			result.append({"role": role, "content": content})

	return result


def _build_tools(tools: list):
	"""OpenAI-format tool schemas pass directly to xAI."""
	if not tools:
		return None
	return tools


class GrokProvider(BaseProvider):
	def chat(self, messages: list, tools: list = None) -> dict:
		try:
			client = _get_client(self.api_key, self.api_base_url)
			oai_messages = _build_messages(messages)
			oai_tools = _build_tools(tools)

			kwargs = {
				"model": self.model,
				"messages": oai_messages,
				"max_tokens": self.max_tokens,
				"temperature": self.temperature,
			}
			if oai_tools:
				kwargs["tools"] = oai_tools
				kwargs["tool_choice"] = "auto"

			response = client.chat.completions.create(**kwargs)
			choice = response.choices[0] if response.choices else None
			msg = choice.message if choice else None

			content = (msg.content or "") if msg else ""
			finish_reason = choice.finish_reason if choice else "stop"

			tool_calls = None
			if msg and msg.tool_calls:
				tool_calls = [
					{
						"id": tc.id,
						"type": "function",
						"function": {
							"name": tc.function.name,
							"arguments": tc.function.arguments,
						},
					}
					for tc in msg.tool_calls
				]
				finish_reason = "tool_calls"

			usage = response.usage
			return {
				"content": content,
				"role": "assistant",
				"tool_calls": tool_calls,
				"finish_reason": finish_reason,
				"usage": {
					"input_tokens": getattr(usage, "prompt_tokens", 0) or 0,
					"output_tokens": getattr(usage, "completion_tokens", 0) or 0,
				},
			}

		except (ProviderRateLimitError, ProviderAuthError, ProviderError):
			raise
		except Exception as exc:
			_wrap_openai_error(exc)

	def stream(self, messages: list, tools: list = None):
		try:
			client = _get_client(self.api_key, self.api_base_url)
			oai_messages = _build_messages(messages)
			oai_tools = _build_tools(tools)

			kwargs = {
				"model": self.model,
				"messages": oai_messages,
				"max_tokens": self.max_tokens,
				"temperature": self.temperature,
				"stream": True,
				"stream_options": {"include_usage": True},
			}
			if oai_tools:
				kwargs["tools"] = oai_tools
				kwargs["tool_choice"] = "auto"

			total_input = 0
			total_output = 0
			finish_reason = "stop"
			accumulated_tool_calls = {}  # index → {id, name, arguments}

			for chunk in client.chat.completions.create(**kwargs):
				choice = chunk.choices[0] if chunk.choices else None
				delta = choice.delta if choice else None

				if delta and delta.content:
					yield {"event": "token", "data": {"delta": delta.content}}

				if delta and delta.tool_calls:
					for tc_delta in delta.tool_calls:
						idx = tc_delta.index
						if idx not in accumulated_tool_calls:
							accumulated_tool_calls[idx] = {
								"id": tc_delta.id or "",
								"name": "",
								"arguments": "",
							}
						if tc_delta.id:
							accumulated_tool_calls[idx]["id"] = tc_delta.id
						if tc_delta.function:
							if tc_delta.function.name:
								accumulated_tool_calls[idx]["name"] += tc_delta.function.name
							if tc_delta.function.arguments:
								accumulated_tool_calls[idx]["arguments"] += tc_delta.function.arguments

				if choice and choice.finish_reason:
					finish_reason = choice.finish_reason

				if chunk.usage:
					total_input = chunk.usage.prompt_tokens or 0
					total_output = chunk.usage.completion_tokens or 0

			# Assemble tool calls list
			tool_calls_list = []
			for idx in sorted(accumulated_tool_calls):
				tc = accumulated_tool_calls[idx]
				tool_calls_list.append({
					"id": tc["id"],
					"type": "function",
					"function": {
						"name": tc["name"],
						"arguments": tc["arguments"],
					},
				})
				yield {
					"event": "tool_start",
					"data": {
						"tool": tc["name"],
						"args": _safe_parse(tc["arguments"]),
					},
				}

			if tool_calls_list:
				finish_reason = "tool_calls"

			yield {
				"event": "done",
				"data": {
					"finish_reason": finish_reason,
					"usage": {"input": total_input, "output": total_output},
					"tool_calls": tool_calls_list or None,
				},
			}

		except (ProviderRateLimitError, ProviderAuthError, ProviderError):
			raise
		except Exception as exc:
			try:
				_wrap_openai_error(exc)
			except ProviderError as pe:
				yield {"event": "error", "data": {"code": type(pe).__name__, "message": str(pe)}}

	def count_tokens(self, messages: list) -> int:
		total_chars = sum(len(str(m.get("content", ""))) for m in messages)
		return max(1, total_chars // 4)

	def supports_tools(self) -> bool:
		return True

	def supports_vision(self) -> bool:
		# grok-2-vision and later support vision
		return "vision" in (self.model or "").lower()

	def get_context_window(self) -> int:
		return 131_072


def _safe_parse(s: str) -> dict:
	try:
		return json.loads(s) if s else {}
	except Exception:
		return {}
