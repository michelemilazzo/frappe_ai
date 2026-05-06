import json
import re

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
			raise ProviderRateLimitError(
				"NVIDIA API quota exceeded. Please wait and try again.",
				retry_after=retry_after,
			) from exc

		if isinstance(exc, AuthenticationError):
			raise ProviderAuthError(
				"NVIDIA API key is invalid. Please check AI Assistant Settings."
			) from exc

		if isinstance(exc, APIStatusError):
			frappe.log_error(frappe.get_traceback(), f"NvidiaProvider API error ({exc.status_code})")
			raise ProviderError(f"NVIDIA API error {exc.status_code}: {exc.message}") from exc

	except ImportError:
		pass

	frappe.log_error(frappe.get_traceback(), f"NvidiaProvider unexpected error: {type(exc).__name__}")
	raise ProviderError(str(exc)) from exc


def _flatten_content(content) -> str:
	"""
	Normalise content to a plain string.
	Some NVIDIA models return content as a structured object or list:
	  {"type": "text", "text": "Hello!"}
	  [{"type": "text", "text": "Hello!"}]
	Extract the text value so we never display raw JSON to the user.
	"""
	if isinstance(content, str):
		return content
	if isinstance(content, dict):
		# {"type": "text", "text": "..."}
		if content.get("type") == "text":
			return content.get("text") or ""
		# {"type": "something_else"} — stringify safely
		return content.get("text") or content.get("content") or ""
	if isinstance(content, list):
		parts = []
		for item in content:
			if isinstance(item, dict) and item.get("type") == "text":
				parts.append(item.get("text") or "")
			elif isinstance(item, str):
				parts.append(item)
		return "".join(parts)
	return str(content) if content is not None else ""


def _build_messages(messages: list) -> list:
	"""Pass messages through in OpenAI format, preserving tool roles."""
	result = []
	for msg in messages:
		role = msg.get("role", "user")
		content = _flatten_content(msg.get("content", "") or "")

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


_CONTENT_BLOCK_TYPES = {"text", "image_url", "image", "document", "tool_result", "tool_use"}


def _extract_tool_calls_from_content(content: str) -> list | None:
	"""
	NVIDIA Llama models emit tool calls as plain JSON in content instead of
	using the tool_calls field. Extract and normalise them.

	Handles: {"name": "fn", "parameters": {...}}
	         {"type": "function", "name": "fn", "parameters": {...}}
	         [{"name": "fn", "parameters": {...}}, ...]

	Explicitly rejects content-block objects like {"type": "text", "text": "..."}.
	"""
	if not content or "{" not in content:
		return None

	stripped = content.strip()

	# Try to parse the whole content as JSON first (most common case)
	candidates = [stripped]

	# Also try to find the outermost JSON object/array if content has surrounding text
	for pat in (r'\[.*\]', r'\{.*\}'):
		m = re.search(pat, stripped, re.DOTALL)
		if m and m.group(0) != stripped:
			candidates.append(m.group(0))

	for candidate in candidates:
		try:
			parsed = json.loads(candidate)
		except (json.JSONDecodeError, ValueError):
			continue

		# Reject content-block objects immediately — these are NOT tool calls
		if isinstance(parsed, dict):
			block_type = parsed.get("type", "")
			if block_type in _CONTENT_BLOCK_TYPES:
				return None
		if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
			if parsed[0].get("type", "") in _CONTENT_BLOCK_TYPES:
				return None

		calls = parsed if isinstance(parsed, list) else [parsed]
		if not isinstance(calls, list):
			continue

		result = []
		for c in calls:
			if not isinstance(c, dict):
				continue
			# Skip content blocks within arrays too
			if c.get("type", "") in _CONTENT_BLOCK_TYPES:
				continue
			name = c.get("name") or c.get("function", {}).get("name", "")
			if not name:
				continue
			params = (
				c.get("parameters")
				or c.get("arguments")
				or c.get("function", {}).get("arguments", {})
				or {}
			)
			result.append({
				"id": f"call_{name}",
				"type": "function",
				"function": {
					"name": name,
					"arguments": json.dumps(params) if isinstance(params, dict) else str(params),
				},
			})
		if result:
			return result

	return None


class NvidiaProvider(BaseProvider):
	def chat(self, messages: list, tools: list = None) -> dict:
		try:
			client = _get_client(self.api_key, self.api_base_url)
			oai_messages = _build_messages(messages)

			kwargs = {
				"model": self.model,
				"messages": oai_messages,
				"max_tokens": self.max_tokens,
				"temperature": self.temperature,
				"top_p": 1.0,
			}
			if tools:
				kwargs["tools"] = tools
				kwargs["tool_choice"] = "auto"

			response = client.chat.completions.create(**kwargs)
			choice = response.choices[0] if response.choices else None
			msg = choice.message if choice else None
			content = _flatten_content((msg.content or "") if msg else "")
			finish_reason = (choice.finish_reason if choice else None) or "stop"

			# Primary: proper tool_calls field
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
				content = ""

			# Fallback: model echoed the call as JSON in content
			if not tool_calls and tools:
				extracted = _extract_tool_calls_from_content(content)
				if extracted:
					tool_calls = extracted
					finish_reason = "tool_calls"
					content = ""

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
			_wrap_nvidia_error(exc)

	def stream(self, messages: list, tools: list = None):
		try:
			client = _get_client(self.api_key, self.api_base_url)
			oai_messages = _build_messages(messages)

			kwargs = {
				"model": self.model,
				"messages": oai_messages,
				"max_tokens": self.max_tokens,
				"temperature": self.temperature,
				"top_p": 1.0,
				"stream": True,
				# Note: stream_options omitted — not supported by all NVIDIA NIM models
			}
			if tools:
				kwargs["tools"] = tools
				kwargs["tool_choice"] = "auto"

			total_input = 0
			total_output = 0
			finish_reason = "stop"
			accumulated_text = ""
			accumulated_tool_calls = {}

			# NVIDIA Llama models stream tool calls as plain JSON text in content
			# with finish_reason="stop" instead of using the tool_calls field.
			# When tools are active we must buffer all content and inspect after
			# the stream ends — we cannot yield tokens until we know it is prose.
			buffered_tokens = [] if tools else None

			for chunk in client.chat.completions.create(**kwargs):
				if not chunk.choices:
					continue

				choice = chunk.choices[0]
				delta = choice.delta if choice else None

				if delta and delta.content:
					piece = _flatten_content(delta.content)
					if piece:
						accumulated_text += piece
						if buffered_tokens is not None:
							buffered_tokens.append(piece)
						else:
							yield {"event": "token", "data": {"delta": piece}}

				if delta and delta.tool_calls:
					for tc_delta in delta.tool_calls:
						idx = tc_delta.index
						if idx not in accumulated_tool_calls:
							accumulated_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
						if tc_delta.id:
							accumulated_tool_calls[idx]["id"] = tc_delta.id
						if tc_delta.function:
							if tc_delta.function.name:
								accumulated_tool_calls[idx]["name"] += tc_delta.function.name
							if tc_delta.function.arguments:
								accumulated_tool_calls[idx]["arguments"] += tc_delta.function.arguments

				if choice.finish_reason:
					finish_reason = choice.finish_reason

			# Build tool calls from proper streamed tool_calls deltas
			tool_calls_list = []
			for idx in sorted(accumulated_tool_calls):
				tc = accumulated_tool_calls[idx]
				if tc["name"]:
					tool_calls_list.append({
						"id": tc["id"] or f"call_{tc['name']}",
						"type": "function",
						"function": {"name": tc["name"], "arguments": tc["arguments"]},
					})

			# Fallback: model wrote tool call JSON in content (finish_reason stays "stop")
			if not tool_calls_list and tools and accumulated_text:
				extracted = _extract_tool_calls_from_content(accumulated_text)
				if extracted:
					tool_calls_list = extracted
					buffered_tokens = []  # discard — was tool JSON, not prose

			if tool_calls_list:
				# It was a tool call — don't yield buffered tokens, emit tool_start events
				finish_reason = "tool_calls"
				for tc in tool_calls_list:
					yield {
						"event": "tool_start",
						"data": {
							"tool": tc["function"]["name"],
							"args": _safe_parse(tc["function"]["arguments"]),
						},
					}
			elif buffered_tokens:
				# Normal prose that was buffered — flush now as token events
				for piece in buffered_tokens:
					yield {"event": "token", "data": {"delta": piece}}

			yield {
				"event": "done",
				"data": {
					"finish_reason": finish_reason or "stop",
					"usage": {"input": total_input, "output": total_output},
					"tool_calls": tool_calls_list or None,
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
		return True

	def supports_vision(self) -> bool:
		return False

	def get_context_window(self) -> int:
		return 128_000


def _safe_parse(s: str) -> dict:
	try:
		return json.loads(s) if s else {}
	except Exception:
		return {}
