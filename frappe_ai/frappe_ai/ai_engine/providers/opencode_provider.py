import httpx
import json
import re
import time
from typing import Any, Dict, List, Optional

import frappe

from frappe_ai.frappe_ai.ai_engine.base_provider import (
	BaseProvider,
	ProviderAuthError,
	ProviderContextLengthError,
	ProviderError,
	ProviderRateLimitError,
)


BASE_URL = "https://opencode.ai"

# ── Routing basato sul prefisso del modello ──────────────────────

API_TYPE_BY_PREFIX = [
	# (prefix, api_type, endpoint_path)
	("o1-", "responses", "/zen/v1/responses"),
	("o3-", "responses", "/zen/v1/responses"),
	("gpt-", "responses", "/zen/v1/responses"),
	("claude-", "messages", "/zen/v1/messages"),
	("minimax-", "messages", "/zen/v1/messages"),
	("gemini-", "gemini", "/zen/v1/models/{model}"),
]

# Modelli noti gratuiti / low-cost su OpenCode
FREE_TIER_MODELS = {
	"glm-4.7-free",
	"glm-4.6",
	"kimi-k2",
	"kimi-k2-thinking",
	"qwen3-coder-32b",
	"qwen3-coder",
	"grok-code-fast-1",
	"big-pickle",
	"minimax-m2.1-free",
	"gemini-3-flash",
	"gemini-3-flash-8b",
}


def _get_api_type(model: str) -> str:
	"""Determine API type from model name prefix."""
	model_lower = model.lower()
	for prefix, api_type, _ in API_TYPE_BY_PREFIX:
		if model_lower.startswith(prefix):
			return api_type
	return "chat_completions"


def _get_endpoint_url(model: str, api_type: str) -> str:
	"""Build the full endpoint URL for the given model and API type."""
	for prefix, atype, path in API_TYPE_BY_PREFIX:
		if model.lower().startswith(prefix) and atype == api_type:
			if "{model}" in path:
				return f"{BASE_URL}{path.format(model=model)}"
			return f"{BASE_URL}{path}"

	# Default fallback
	return f"{BASE_URL}/zen/v1/chat/completions"


# ── Tool schema conversion per API type ──────────────────────────

def _build_tool_payload(tools: list, api_type: str) -> dict:
	"""Convert internal tool schema to the format expected by the API type."""
	if not tools:
		return {}

	if api_type == "responses":
		return {
			"tools": [
				{
					"type": "function",
					"function": {
						"name": t["function"]["name"],
						"description": t["function"].get("description", ""),
						"parameters": t["function"].get("parameters", {}),
					},
				}
				for t in tools
			]
		}

	elif api_type == "messages":
		return {
			"tools": [
				{
					"name": t["function"]["name"],
					"description": t["function"].get("description", ""),
					"input_schema": t["function"].get("parameters", {}),
				}
				for t in tools
			]
		}

	elif api_type == "gemini":
		return {
			"tools": [
				{
					"functionDeclarations": [
						{
							"name": t["function"]["name"],
							"description": t["function"].get("description", ""),
							"parameters": t["function"].get("parameters", {}),
						}
					]
				}
			]
		}

	else:  # chat_completions
		return {
			"functions": [
				{
					"name": t["function"]["name"],
					"description": t["function"].get("description", ""),
					"parameters": t["function"].get("parameters", {}),
				}
				for t in tools
			]
		}


# ── Response parsing helpers ─────────────────────────────────────

def _extract_tool_calls_from_responses(data: dict) -> list:
	"""Extract tool calls from OpenCode Responses API output."""
	for choice in data.get("choices", []):
		msg = choice.get("message", choice)
		raw_tools = msg.get("tool_calls") or msg.get("tools_calls") or []
		return [
			{
				"id": (fn := tc.get("function", tc)).get("name", "unknown"),
				"type": "function",
				"function": {
					"name": fn.get("name", "unknown"),
					"arguments": json.dumps(fn.get("arguments", {})),
				},
			}
			for tc in raw_tools
		]
	return []


def _extract_tool_calls_from_messages(data: dict) -> list:
	"""Extract tool calls from Anthropic-style Messages API output."""
	tool_calls = []
	for block in data.get("content", []):
		if block.get("type") == "tool_use":
			tool_calls.append({
				"id": block.get("id", "unknown"),
				"type": "function",
				"function": {
					"name": block.get("name", "unknown"),
					"arguments": json.dumps(block.get("input", {})),
				},
			})
	return tool_calls


def _parse_finish_reason(data: dict, api_type: str, tool_calls: list = None) -> str:
	"""Extract finish_reason from response based on API type."""
	if tool_calls:
		return "tool_calls"

	if api_type == "responses":
		for choice in data.get("choices", []):
			fr = choice.get("finish_reason", "stop")
			if fr == "max_tokens":
				return "length"
			return fr
		return "stop"

	elif api_type == "messages":
		fr = data.get("stop_reason", "stop")
		return {"end_turn": "stop", "max_tokens": "length"}.get(fr, fr)

	elif api_type == "gemini":
		for candidate in data.get("candidates", []):
			fr = candidate.get("finishReason", "STOP")
			return {"STOP": "stop", "MAX_TOKENS": "length"}.get(fr, "stop")
		return "stop"

	else:  # chat_completions
		for choice in data.get("choices", []):
			fr = choice.get("finish_reason", "stop")
			if fr == "length":
				return "length"
			return fr
		return "stop"


def _parse_sse_event(line: str) -> Optional[dict]:
	"""Parse a single SSE data line into a Python dict."""
	line = line.strip()
	if not line.startswith("data:"):
		return None
	data_str = line[5:].strip()
	if data_str in ("[DONE]", ""):
		return {"event": "done", "data": {}}
	try:
		return json.loads(data_str)
	except json.JSONDecodeError:
		return {"event": "raw", "data": {"text": data_str}}


# ── Main Provider ────────────────────────────────────────────────

class OpenCodeProvider(BaseProvider):
	"""
	Provider for OpenCode.ai Zen API.

	Supports multiple API types automatically based on model name:
	- Responses API  → GPT family (o1, o3, gpt-5, gpt-5.1, etc.)
	- Messages API   → Claude family (claude-sonnet-4-5, etc.)
	- Google GenAI    → Gemini (gemini-3-pro, gemini-3-flash, etc.)
	- Chat Completions → GLM, Kimi, Grok, Qwen, BigPickle
	"""

	def __init__(self, settings: Dict[str, Any]):
		super().__init__(settings)
		self.api_key = settings.get("api_key", "")
		self.model = settings.get("model", "gpt-5.2")
		self.api_type = _get_api_type(self.model)
		self.endpoint_url = _get_endpoint_url(self.model, self.api_type)
		self._client: Optional[httpx.Client] = None

	@property
	def client(self) -> httpx.Client:
		if self._client is None or self._client.is_closed:
			self._client = httpx.Client(
				base_url=BASE_URL,
				headers={
					"Authorization": f"Bearer {self.api_key}",
					"Content-Type": "application/json",
				},
				timeout=httpx.Timeout(120.0, connect=30.0),
			)
		return self._client

	def _build_request_body(
		self,
		messages: List[Dict],
		tools: List[Dict] = None,
		stream: bool = False,
	) -> Dict:
		"""Build the request body appropriate for the detected API type."""
		body: Dict[str, Any] = {
			"model": self.model,
			"max_tokens": self.max_tokens,
			"temperature": self.temperature,
			"stream": stream,
		}

		if self.api_type == "messages":
			# Claude-style: separate `system` field + message list
			system_msgs = [m for m in messages if m.get("role") == "system"]
			user_msgs = [m for m in messages if m.get("role") != "system"]

			content_items: List[Dict] = []
			for msg in user_msgs:
				role = msg.get("role", "user")
				content = msg.get("content", "") or ""
				if role == "assistant":
					content_items.append({"type": "text", "text": content})
				elif role in ("user", "tool"):
					if role == "tool":
						content_items.append({
							"type": "tool_result",
							"tool_use_id": msg.get("tool_call_id", ""),
							"content": content,
						})
					else:
						content_items.append({"type": "text", "text": content})

			body["messages"] = content_items
			if system_msgs:
				body["system"] = system_msgs[0].get("content", "")
		else:
			# All other API types: pass messages as-is
			body["messages"] = messages

		# Add tool definitions
		tool_payload = _build_tool_payload(tools or [], self.api_type)
		body.update(tool_payload)

		return body

	# ── Synchronous chat ────────────────────────────────────────────

	def chat(self, messages: List[Dict], tools: List[Dict] = None) -> Dict:
		body = self._build_request_body(messages, tools, stream=False)
		try:
			resp = self.client.post(self.endpoint_url, json=body)
			resp.raise_for_status()
			data = resp.json()
			return self._parse_response(data)
		except httpx.HTTPStatusError as exc:
			self._handle_http_error(exc)

	# ── Response parsing ───────────────────────────────────────────

	def _parse_response(self, data: dict) -> dict:
		"""Parse API response into standardized format."""
		usage = data.get("usage", {})

		if self.api_type == "responses":
			choices = data.get("choices", [])
			if choices:
				msg = choices[0].get("message", choices[0])
				content = msg.get("content", "")
				tool_calls = _extract_tool_calls_from_responses(data)
			else:
				content = data.get("output_text", "")
				tool_calls = None

		elif self.api_type == "messages":
			content_parts = []
			tool_calls = []
			for item in data.get("content", []):
				if item.get("type") == "text":
					content_parts.append(item.get("text", ""))
				elif item.get("type") == "tool_use":
					tool_calls.append({
						"id": item.get("id", ""),
						"type": "function",
						"function": {
							"name": item.get("name", ""),
							"arguments": json.dumps(item.get("input", {})),
						},
					})
			content = "".join(content_parts)
			if not tool_calls:
				tool_calls = None

		elif self.api_type == "gemini":
			candidates = data.get("candidates", [])
			if candidates:
				c = candidates[0]
				parts = c.get("content", {}).get("parts", [])
				content_parts = []
				tool_calls = []
				for part in parts:
					if "text" in part:
						content_parts.append(part["text"])
					elif "functionCall" in part:
						fc = part["functionCall"]
						tool_calls.append({
							"id": fc.get("name", ""),
							"type": "function",
							"function": {
								"name": fc.get("name", ""),
								"arguments": json.dumps(fc.get("args", {})),
							},
						})
				content = "".join(content_parts)
				if not tool_calls:
					tool_calls = None
				else:
					# Prefer finish_reason from tool calls
					pass
			else:
				content = ""
				tool_calls = None
		else:
			# chat_completions (GLM, Kimi, Grok, Qwen, etc.)
			choices = data.get("choices", [])
			if choices:
				msg = choices[0].get("message", {})
				content = msg.get("content", "") or ""
				raw_tc = msg.get("tool_calls") or msg.get("function_call")
				if raw_tc:
					if isinstance(raw_tc, list):
						tool_calls = []
						for tc in raw_tc:
							fn = tc.get("function", {})
							tool_calls.append({
								"id": tc.get("id", fn.get("name", "")),
								"type": "function",
								"function": {
									"name": fn.get("name", ""),
									"arguments": fn.get("arguments", "{}")
									if isinstance(fn.get("arguments"), str)
									else json.dumps(fn.get("arguments", {})),
								},
							})
					else:
						fn = raw_tc.get("function", {})
						tool_calls = [{
							"id": fn.get("name", ""),
							"type": "function",
							"function": {
								"name": fn.get("name", ""),
								"arguments": fn.get("arguments", "{}")
								if isinstance(fn.get("arguments"), str)
								else json.dumps(fn.get("arguments", {})),
							},
						}]
				else:
					tool_calls = None
				finish_reason_raw = choices[0].get("finish_reason", "stop")
			else:
				content = ""
				tool_calls = None
				finish_reason_raw = "stop"

		finish_reason = _parse_finish_reason(data, self.api_type, tool_calls)

		return {
			"content": content,
			"role": "assistant",
			"tool_calls": tool_calls,
			"finish_reason": finish_reason,
			"usage": {
				"input_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0,
				"output_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0,
			},
		}

	# ── Streaming ───────────────────────────────────────────────────

	def stream(self, messages: List[Dict], tools: List[Dict] = None):
		body = self._build_request_body(messages, tools, stream=True)
		try:
			with self.client.stream("POST", self.endpoint_url, json=body) as resp:
				resp.raise_for_status()
				yield from self._stream_events(resp, tools)
		except httpx.HTTPStatusError as exc:
			self._handle_http_error(exc)

	def _stream_events(self, response, tools: List[Dict] = None):
		"""Parse SSE stream and yield standardized events."""
		buffer = ""
		accumulated_text = ""
		accumulated_tc = []
		full_usage = {"input_tokens": 0, "output_tokens": 0}
		seen_content_block_start = False

		for chunk in response.iter_text():
			buffer += chunk
			while "\n\n" in buffer:
				block, buffer = buffer.split("\n\n", 1)
				parsed = _parse_sse_event(block.strip())
				if parsed is None:
					continue

				data = parsed.get("data", {})
				if not isinstance(data, dict):
					continue

				event_type = parsed.get("event", "")

				# ── Responses API (GPT models) ──
				if self.api_type == "responses":
					if event_type == "response.output_text.delta":
						delta = data.get("delta", "")
						accumulated_text += delta
						yield {"event": "token", "data": {"delta": delta}}
					elif event_type == "response.function_call_arguments.delta":
						yield {"event": "tool_start", "data": {
							"tool": "function",
							"args": data.get("delta", ""),
						}}
					elif event_type == "response.done":
						usage = data.get("usage", {})
						full_usage["input_tokens"] = usage.get("prompt_tokens", 0) or 0
						full_usage["output_tokens"] = usage.get("completion_tokens", 0) or 0
						yield {
							"event": "done",
							"data": {
								"finish_reason": data.get("finish_reason", "stop"),
								"usage": full_usage,
								"tool_calls": accumulated_tc or None,
							},
						}
					elif "content" in data and isinstance(data["content"], str):
						accumulated_text += data["content"]
						yield {"event": "token", "data": {"delta": data["content"]}}

				# ── Messages API (Claude models) ──
				elif self.api_type == "messages":
					if event_type == "content_block_start":
						seen_content_block_start = True
					elif event_type == "content_block_delta":
						delta = data.get("delta", {})
						text = delta.get("text", "")
						if text:
							accumulated_text += text
							yield {"event": "token", "data": {"delta": text}}
					elif event_type == "content_block_stop":
						seen_content_block_start = False
					elif event_type == "message_delta":
						usage = data.get("usage", {})
						full_usage["input_tokens"] = usage.get("input_tokens", 0) or 0
						full_usage["output_tokens"] = usage.get("output_tokens", 0) or 0
						yield {
							"event": "done",
							"data": {
								"finish_reason": data.get("delta", {}).get("stop_reason", "stop"),
								"usage": full_usage,
								"tool_calls": accumulated_tc or None,
							},
						}
					elif "content" in data and isinstance(data["content"], str):
						accumulated_text += data["content"]
						yield {"event": "token", "data": {"delta": data["content"]}}

				# ── Gemini (Google GenAI compatible) ──
				elif self.api_type == "gemini":
					if "candidates" in data:
						for c in data["candidates"]:
							for part in c.get("content", {}).get("parts", []):
								if "text" in part:
									accumulated_text += part["text"]
									yield {"event": "token", "data": {"delta": part["text"]}}
								elif "functionCall" in part:
									fc = part["functionCall"]
									accumulated_tc.append({
										"id": fc.get("name", ""),
										"type": "function",
										"function": {
											"name": fc.get("name", ""),
											"arguments": json.dumps(fc.get("args", {})),
										},
									})
							fr = c.get("finishReason", "")
							if fr:
								full_usage = {
									"input_tokens": data.get("usageMetadata", {}).get("promptTokenCount", 0),
									"output_tokens": data.get("usageMetadata", {}).get("candidatesTokenCount", 0),
								}
								yield {
									"event": "done",
									"data": {
										"finish_reason": {"STOP": "stop", "MAX_TOKENS": "length"}.get(fr, "stop"),
										"usage": full_usage,
										"tool_calls": accumulated_tc or None,
									},
								}
					elif "usageMetadata" in data:
						full_usage = {
							"input_tokens": data["usageMetadata"].get("promptTokenCount", 0),
							"output_tokens": data["usageMetadata"].get("candidatesTokenCount", 0),
						}
					elif "content" in data and isinstance(data["content"], str):
						accumulated_text += data["content"]
						yield {"event": "token", "data": {"delta": data["content"]}}

				# ── Chat Completions (GLM, Kimi, Grok, Qwen, etc.) ──
				else:
					choices = data.get("choices", [])
					if choices:
						delta = choices[0].get("delta", {})
						content_delta = delta.get("content", "") or ""
						if content_delta:
							accumulated_text += content_delta
							yield {"event": "token", "data": {"delta": content_delta}}

						tc = delta.get("tool_calls")
						if tc:
							for t in tc:
								fn = t.get("function", {})
								accumulated_tc.append({
									"id": t.get("id", ""),
									"type": "function",
									"function": {
										"name": fn.get("name", ""),
										"arguments": fn.get("arguments", "{}")
										if isinstance(fn.get("arguments"), str)
										else json.dumps(fn.get("arguments", {})),
									},
								})

						finish = choices[0].get("finish_reason")
						if finish:
							usage = data.get("usage", {})
							full_usage["input_tokens"] = usage.get("prompt_tokens", 0) or 0
							full_usage["output_tokens"] = usage.get("completion_tokens", 0) or 0
							yield {
								"event": "done",
								"data": {
									"finish_reason": finish,
									"usage": full_usage,
									"tool_calls": accumulated_tc or None,
								},
							}

				# ── Done generico ──
				elif event_type == "done":
					usage = data.get("usage", {})
					full_usage["input_tokens"] = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
					full_usage["output_tokens"] = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
					yield {
						"event": "done",
						"data": {
							"finish_reason": data.get("finish_reason", "stop"),
							"usage": full_usage,
							"tool_calls": accumulated_tc or None,
						},
					}

	# ── Token counting ──────────────────────────────────────────────

	def count_tokens(self, messages: List[Dict]) -> int:
		"""Approximate token count using character heuristic."""
		total_chars = sum(len(str(m.get("content", ""))) for m in messages)
		return max(1, total_chars // 4)

	# ── Capabilities ────────────────────────────────────────────────

	def supports_tools(self) -> bool:
		return True

	def supports_vision(self) -> bool:
		return True

	def get_context_window(self) -> int:
		windows = {
			"o1-": 200_000,
			"o3-": 200_000,
			"gpt-5.2": 200_000,
			"gpt-5.1": 200_000,
			"gpt-5": 200_000,
			"claude-sonnet-4-5": 200_000,
			"claude-opus-4-5": 200_000,
			"claude-haiku-4-5": 200_000,
			"gemini-3-pro": 1_000_000,
			"gemini-3-flash": 1_000_000,
			"glm-4.6": 128_000,
			"glm-4.7": 128_000,
			"kimi-k2": 128_000,
			"grok-code": 128_000,
			"qwen3-coder": 128_000,
		}
		if self.model in windows:
			return windows[self.model]
		for prefix, size in windows.items():
			if self.model.startswith(prefix):
				return size
		return 128_000

	# ── Error handling ──────────────────────────────────────────────

	def _handle_http_error(self, exc: httpx.HTTPStatusError):
		"""Convert HTTP errors to provider-specific exceptions."""
		status = exc.response.status_code
		try:
			body = exc.response.json()
			msg = body.get("error", {}).get("message", str(body))
		except Exception:
			msg = exc.response.text[:500]

		if status == 401 or status == 403:
			raise ProviderAuthError(f"OpenCode auth error: {msg}") from exc
		elif status == 429:
			retry_after = None
			retry_header = exc.response.headers.get("retry-after")
			try:
				retry_after = int(retry_header) if retry_header else None
			except (ValueError, TypeError):
				pass
			raise ProviderRateLimitError(
				f"OpenCode rate limit exceeded: {msg}",
				retry_after=retry_after,
			) from exc
		elif status == 400:
			raise ProviderError(f"OpenCode bad request: {msg}") from exc
		elif status >= 500:
			raise ProviderError(f"OpenCode server error ({status}): {msg}") from exc
		else:
			raise ProviderError(f"OpenCode API error ({status}): {msg}") from exc