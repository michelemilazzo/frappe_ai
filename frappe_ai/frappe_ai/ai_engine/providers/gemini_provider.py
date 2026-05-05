import json

import frappe

from frappe_ai.frappe_ai.ai_engine.base_provider import (
	BaseProvider,
	ProviderAuthError,
	ProviderContextLengthError,
	ProviderError,
	ProviderRateLimitError,
)


def _get_client(api_key: str):
	from google import genai

	return genai.Client(api_key=api_key)


def _messages_to_contents(messages: list):
	"""Convert OpenAI-style messages to google-genai Contents list."""
	from google.genai import types

	system_parts = []
	contents = []

	for msg in messages:
		role = msg.get("role", "user")
		content = msg.get("content", "") or ""

		if role == "system":
			system_parts.append(content)
			continue

		if role == "tool":
			fn_name = msg.get("tool_call_id", "tool_result")
			result_text = content if isinstance(content, str) else json.dumps(content)
			contents.append(
				types.Content(
					role="user",
					parts=[
						types.Part.from_function_response(
							name=fn_name,
							response={"result": result_text},
						)
					],
				)
			)
			continue

		genai_role = "model" if role == "assistant" else "user"
		text = content if isinstance(content, str) else json.dumps(content)

		# Inject system context into the first user turn
		if genai_role == "user" and system_parts and not contents:
			system_block = "\n\n".join(system_parts)
			text = f"[System Instructions]\n{system_block}\n\n[User Message]\n{text}"
			system_parts = []

		contents.append(types.Content(role=genai_role, parts=[types.Part.from_text(text=text)]))

	return contents


def _tools_to_genai(tools: list):
	"""Convert OpenAI-style function schemas to google-genai Tool."""
	if not tools:
		return None
	from google.genai import types

	declarations = []
	for tool in tools:
		fn = tool.get("function", tool)
		params = fn.get("parameters", {})

		declarations.append(
			types.FunctionDeclaration(
				name=fn["name"],
				description=fn.get("description", ""),
				parameters=_json_schema_to_genai(params),
			)
		)
	return [types.Tool(function_declarations=declarations)]


def _json_schema_to_genai(schema: dict):
	"""Recursively convert a JSON Schema dict to a google-genai types.Schema."""
	from google.genai import types

	json_type = schema.get("type", "string")
	genai_type = _json_type_to_genai(json_type)
	description = schema.get("description", "")

	if json_type == "object":
		properties = {}
		for k, v in schema.get("properties", {}).items():
			properties[k] = _json_schema_to_genai(v)
		return types.Schema(
			type=genai_type,
			description=description,
			properties=properties,
			required=schema.get("required", []),
		)

	if json_type == "array":
		items_schema = schema.get("items", {"type": "string"})
		return types.Schema(
			type=genai_type,
			description=description,
			items=_json_schema_to_genai(items_schema),
		)

	return types.Schema(type=genai_type, description=description)


def _json_type_to_genai(json_type: str) -> str:
	return {
		"string": "STRING",
		"integer": "INTEGER",
		"number": "NUMBER",
		"boolean": "BOOLEAN",
		"array": "ARRAY",
		"object": "OBJECT",
	}.get(json_type, "STRING")


def _extract_retry_seconds(exc) -> int | None:
	"""Pull retryDelay from ClientError.details response body."""
	try:
		# exc.details is the raw response_json dict from the SDK
		body = getattr(exc, "details", None) or {}
		details = body.get("error", {}).get("details", [])
		for d in details:
			delay = d.get("retryDelay", "")
			if delay:
				return int(str(delay).rstrip("s").strip())
	except Exception:
		pass
	return None


def _wrap_google_error(exc):
	import traceback

	import frappe

	# google-genai SDK: ClientError/ServerError both inherit APIError
	# The HTTP status is stored as exc.code (NOT exc.status_code)
	try:
		from google.genai import errors as genai_errors

		if isinstance(exc, genai_errors.APIError):
			# exc.code is the numeric HTTP status (429, 400, 403 …)
			# exc.status is the string status ("RESOURCE_EXHAUSTED" …)
			http_code = getattr(exc, "code", 0) or 0
			status_str = getattr(exc, "status", "") or ""

			if http_code == 429 or "RESOURCE_EXHAUSTED" in status_str:
				retry_after = _extract_retry_seconds(exc)
				msg = "Gemini API quota exceeded. Please wait and try again."
				raise ProviderRateLimitError(msg, retry_after=retry_after) from exc

			if http_code in (401, 403) or "PERMISSION_DENIED" in status_str or "UNAUTHENTICATED" in status_str:
				raise ProviderAuthError(f"Gemini API auth error: {exc.message or exc}") from exc

			if http_code == 400 or "INVALID_ARGUMENT" in status_str:
				tb = traceback.format_exc()
				frappe.log_error(tb, f"GeminiProvider bad request ({http_code})")
				raise ProviderError(f"Gemini API bad request: {exc.message or exc}") from exc

			tb = traceback.format_exc()
			frappe.log_error(tb, f"GeminiProvider API error ({http_code} {status_str})")
			raise ProviderError(f"Gemini API error {http_code}: {exc.message or exc}") from exc

	except ImportError:
		pass

	# Fallback: google-api-core exceptions (older path, kept for safety)
	try:
		from google.api_core import exceptions as gexc

		if isinstance(exc, gexc.ResourceExhausted):
			raise ProviderRateLimitError("Gemini API quota exceeded. Please try again shortly.") from exc
		if isinstance(exc, gexc.PermissionDenied):
			raise ProviderAuthError(str(exc)) from exc
		if isinstance(exc, gexc.InvalidArgument):
			raise ProviderError(str(exc)) from exc
	except ImportError:
		pass

	tb = traceback.format_exc()
	frappe.log_error(tb, f"GeminiProvider unexpected error: {type(exc).__name__}")
	raise ProviderError(str(exc)) from exc


class GeminiProvider(BaseProvider):
	def chat(self, messages: list, tools: list = None) -> dict:
		try:
			client = _get_client(self.api_key)
			contents = _messages_to_contents(messages)
			genai_tools = _tools_to_genai(tools) if tools else None

			from google.genai import types

			config = types.GenerateContentConfig(
				max_output_tokens=self.max_tokens,
				temperature=self.temperature,
				tools=genai_tools or [],
			)

			response = client.models.generate_content(
				model=self.model,
				contents=contents,
				config=config,
			)

			candidate = response.candidates[0] if response.candidates else None
			text_parts = []
			tool_calls = []

			if candidate and candidate.content and candidate.content.parts:
				for part in candidate.content.parts:
					if part.text:
						text_parts.append(part.text)
					if part.function_call:
						fc = part.function_call
						tool_calls.append({
							"id": fc.name,
							"type": "function",
							"function": {
								"name": fc.name,
								"arguments": json.dumps(dict(fc.args) if fc.args else {}),
							},
						})

			finish_reason = "stop"
			if candidate and candidate.finish_reason:
				fr = str(candidate.finish_reason)
				if "MAX_TOKENS" in fr:
					finish_reason = "length"
				elif tool_calls:
					finish_reason = "tool_calls"

			usage = response.usage_metadata
			return {
				"content": "".join(text_parts),
				"role": "assistant",
				"tool_calls": tool_calls or None,
				"finish_reason": finish_reason,
				"usage": {
					"input_tokens": getattr(usage, "prompt_token_count", 0) or 0,
					"output_tokens": getattr(usage, "candidates_token_count", 0) or 0,
				},
			}
		except (ProviderRateLimitError, ProviderAuthError, ProviderError):
			raise
		except Exception as exc:
			_wrap_google_error(exc)

	def stream(self, messages: list, tools: list = None):
		try:
			client = _get_client(self.api_key)
			contents = _messages_to_contents(messages)
			genai_tools = _tools_to_genai(tools) if tools else None

			from google.genai import types

			config = types.GenerateContentConfig(
				max_output_tokens=self.max_tokens,
				temperature=self.temperature,
				tools=genai_tools or [],
			)

			total_input = 0
			total_output = 0
			finish_reason = "stop"
			accumulated_tool_calls = []

			for chunk in client.models.generate_content_stream(
				model=self.model,
				contents=contents,
				config=config,
			):
				if not chunk.candidates:
					continue

				candidate = chunk.candidates[0]
				parts = candidate.content.parts if (candidate.content and candidate.content.parts) else []

				for part in parts:
					if part.text:
						yield {"event": "token", "data": {"delta": part.text}}
					if part.function_call:
						fc = part.function_call
						call = {
							"id": fc.name,
							"type": "function",
							"function": {
								"name": fc.name,
								"arguments": json.dumps(dict(fc.args) if fc.args else {}),
							},
						}
						accumulated_tool_calls.append(call)
						yield {
							"event": "tool_start",
							"data": {"tool": fc.name, "args": dict(fc.args) if fc.args else {}},
						}

				if candidate.finish_reason:
					fr = str(candidate.finish_reason)
					if "MAX_TOKENS" in fr:
						finish_reason = "length"
					elif accumulated_tool_calls:
						finish_reason = "tool_calls"

				if chunk.usage_metadata:
					total_input = getattr(chunk.usage_metadata, "prompt_token_count", 0) or 0
					total_output = getattr(chunk.usage_metadata, "candidates_token_count", 0) or 0

			yield {
				"event": "done",
				"data": {
					"finish_reason": finish_reason,
					"usage": {"input": total_input, "output": total_output},
					"tool_calls": accumulated_tool_calls or None,
				},
			}

		except (ProviderRateLimitError, ProviderAuthError, ProviderError):
			raise
		except Exception as exc:
			try:
				_wrap_google_error(exc)
			except ProviderError as pe:
				yield {"event": "error", "data": {"code": type(pe).__name__, "message": str(pe)}}

	def count_tokens(self, messages: list) -> int:
		try:
			client = _get_client(self.api_key)
			contents = _messages_to_contents(messages)
			response = client.models.count_tokens(model=self.model, contents=contents)
			return response.total_tokens or 0
		except Exception:
			total_chars = sum(len(str(m.get("content", ""))) for m in messages)
			return max(1, total_chars // 4)

	def supports_tools(self) -> bool:
		return True

	def supports_vision(self) -> bool:
		return True

	def get_context_window(self) -> int:
		return 1_000_000
