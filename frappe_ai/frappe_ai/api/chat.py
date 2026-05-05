import json
import re
from datetime import date, datetime
from decimal import Decimal

import frappe
from werkzeug.wrappers import Response

from frappe_ai.frappe_ai.ai_engine.base_provider import (
	ProviderAuthError,
	ProviderError,
	ProviderRateLimitError,
)

# Regex that matches a raw tool-call JSON blob that some models (NVIDIA Llama)
# emit as plain text content instead of via the tool_calls field.
_TOOL_CALL_JSON_RE = re.compile(
	r'^\s*\{[^{}]*"(?:type|name)"\s*:\s*"(?:function|[a-z_]+)"[^{}]*\}\s*$',
	re.DOTALL,
)


def _strip_tool_call_json(text: str) -> str:
	"""Return empty string if the entire text is a raw tool-call JSON blob."""
	if not text or "{" not in text:
		return text
	if _TOOL_CALL_JSON_RE.match(text):
		return ""
	# Also catch array of tool calls: [{...}]
	stripped = text.strip()
	if stripped.startswith("[") and stripped.endswith("]"):
		try:
			parsed = json.loads(stripped)
			if isinstance(parsed, list) and all(
				isinstance(i, dict) and ("name" in i or "type" in i) for i in parsed
			):
				return ""
		except (json.JSONDecodeError, ValueError):
			pass
	return text


class _FrappeEncoder(json.JSONEncoder):
	def default(self, o):
		if isinstance(o, (datetime, date)):
			return o.isoformat()
		if isinstance(o, Decimal):
			return float(o)
		try:
			return super().default(o)
		except TypeError:
			return str(o)


def _sse(event: str, data: dict) -> str:
	return f"event: {event}\ndata: {json.dumps(data, cls=_FrappeEncoder)}\n\n"


def _require_conversation(conversation_id: str, user: str):
	doc = frappe.get_doc("AI Conversation", conversation_id)
	if doc.owner != user and "System Manager" not in frappe.get_roles(user):
		frappe.throw("Access denied.", frappe.PermissionError)
	return doc


def _abort_key(user: str, conversation_id: str) -> str:
	return f"ai_abort_{user}_{conversation_id}"


def _auto_title(text: str) -> str:
	clean = re.sub(r"[^\w\s]", "", text).strip()
	return clean[:60] if clean else "New Conversation"


@frappe.whitelist()
def stream_message(conversation_id: str, message: str, attachment: str = None):
	"""
	Validate input and save the user message synchronously, then return a
	streaming Response whose generator runs the AI call and DB saves.
	frappe.local stays alive for the full generator lifetime (ClosingIterator).
	"""
	# --- synchronous pre-flight ---
	if not conversation_id:
		return _make_response([_sse("error", {"code": "invalid_input", "message": "conversation_id is required."})])

	msg = (message or "").strip()
	if not msg:
		return _make_response([_sse("error", {"code": "invalid_input", "message": "Message cannot be blank."})])

	if len(msg) > 32000:
		return _make_response([_sse("error", {"code": "invalid_input", "message": "Message too long (max 32,000 characters)."})])

	user = frappe.session.user

	try:
		conv_doc = _require_conversation(conversation_id, user)
	except frappe.PermissionError:
		return _make_response([_sse("error", {"code": "forbidden", "message": "Access denied."})])

	attach = attachment
	if attach:
		if not frappe.db.exists("File", {"name": attach, "attached_to_name": user}):
			attach = None

	from frappe_ai.frappe_ai.ai_engine.rate_limiter import check_and_increment
	from frappe_ai.frappe_ai.ai_engine.router import get_provider, get_settings

	try:
		settings = get_settings()
		check_and_increment(user, settings)
	except ProviderRateLimitError as exc:
		retry_after = getattr(exc, "retry_after", None)
		user_msg = str(exc)
		if retry_after:
			user_msg = f"{user_msg} Retry in {retry_after}s."
		return _make_response([_sse("error", {"code": "rate_limit", "message": user_msg, "retry_after": retry_after})])
	except Exception:
		frappe.log_error(frappe.get_traceback(), "AI stream_message settings error")
		return _make_response([_sse("error", {"code": "server_error", "message": "Unexpected error. Please try again."})])

	provider = get_provider(settings)

	# Save user message before streaming begins
	input_tokens = 0
	try:
		input_tokens = provider.count_tokens([{"role": "user", "content": msg}])
	except Exception:
		pass

	conv_doc.append(
		"messages",
		{
			"role": "user",
			"content": msg,
			"input_tokens": input_tokens,
			"timestamp": frappe.utils.now(),
			"attachment": attach,
		},
	)
	conv_doc.save(ignore_permissions=False)
	frappe.db.commit()

	# Build context and tools before generator (reads DB — safe here)
	from frappe_ai.frappe_ai.ai_engine.context_manager import build_context

	context_messages = build_context(conversation_id, msg, user, settings)

	tools = []
	if settings.get("tool_calling_enabled"):
		from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import get_tools_for_llm

		tools = get_tools_for_llm(user)

	# Snapshot mutable state needed inside the generator
	is_new_conversation = conv_doc.title == "New Conversation"

	return _make_response(_generate_stream(
		conversation_id=conversation_id,
		user=user,
		provider=provider,
		context_messages=context_messages,
		tools=tools,
		settings=settings,
		msg=msg,
		is_new_conversation=is_new_conversation,
	))


def _generate_stream(
	conversation_id: str,
	user: str,
	provider,
	context_messages: list,
	tools: list,
	settings: dict,
	msg: str,
	is_new_conversation: bool,
):
	"""
	Generator that runs inside the Werkzeug ClosingIterator.
	frappe.local (db, cache, session) is fully available here.
	"""
	from frappe_ai.frappe_ai.ai_engine.agents.agent_runner import run as agent_run

	full_text = ""
	final_usage = {"input_tokens": 0, "output_tokens": 0}
	aborted = False
	abort_key = _abort_key(user, conversation_id)

	try:
		for evt in _iter_agent_events(agent_run, context_messages, provider, user, tools):
			# Check abort before yielding each event
			if frappe.cache().get_value(abort_key):
				aborted = True
				break

			event_type = evt.get("event")
			data = evt.get("data", {})

			if event_type == "token":
				delta = data.get("delta", "")
				full_text += delta
				yield _sse("token", {"delta": delta})

			elif event_type == "tool_start":
				yield _sse("tool_start", {"tool": data.get("tool", ""), "args": data.get("args", {})})

			elif event_type == "tool_result":
				yield _sse("tool_result", {"tool": data.get("tool", ""), "result": data.get("result", {})})

			elif event_type == "done":
				usage = data.get("usage", {})
				final_usage["input_tokens"] = usage.get("input", 0)
				final_usage["output_tokens"] = usage.get("output", 0)
				yield _sse(
					"done",
					{
						"finish_reason": data.get("finish_reason", "stop"),
						"usage": {"input": final_usage["input_tokens"], "output": final_usage["output_tokens"]},
					},
				)

			elif event_type == "error":
				err_msg = data.get("message", "")
				err_code = data.get("code", "provider_error")
				frappe.log_error(
					f"Provider error during stream\nCode: {err_code}\nMessage: {err_msg}",
					"AI stream_message provider event error",
				)
				yield _sse("error", {"code": err_code, "message": err_msg})

	except ProviderRateLimitError as exc:
		retry_after = getattr(exc, "retry_after", None)
		user_msg = str(exc)
		if retry_after:
			user_msg = f"{user_msg} Retry in {retry_after}s."
		yield _sse("error", {"code": "rate_limit", "message": user_msg, "retry_after": retry_after})
		return
	except ProviderAuthError:
		frappe.log_error(frappe.get_traceback(), "AI stream_message auth error")
		yield _sse("error", {"code": "auth_error", "message": "Invalid API key. Please check AI Assistant Settings."})
		return
	except ProviderError as exc:
		frappe.log_error(frappe.get_traceback(), "AI stream_message provider error")
		yield _sse("error", {"code": "provider_error", "message": str(exc)})
		return
	except Exception:
		frappe.log_error(frappe.get_traceback(), "AI stream_message unexpected error")
		yield _sse("error", {"code": "server_error", "message": "Unexpected error. Please try again."})
		return

	# DB saves after streaming completes
	if not aborted:
		try:
			full_text = _strip_tool_call_json(full_text)
			conv_doc = frappe.get_doc("AI Conversation", conversation_id)
			conv_doc.append(
				"messages",
				{
					"role": "assistant",
					"content": full_text,
					"output_tokens": final_usage["output_tokens"],
					"finish_reason": "stop",
					"timestamp": frappe.utils.now(),
				},
			)
			conv_doc.total_input_tokens = (conv_doc.total_input_tokens or 0) + final_usage["input_tokens"]
			conv_doc.total_output_tokens = (conv_doc.total_output_tokens or 0) + final_usage["output_tokens"]
			snippet = full_text[:120].strip()
			conv_doc.last_message = (snippet + "…") if len(full_text) > 120 else snippet
			conv_doc.save(ignore_permissions=False)
			_save_usage_log(user, settings, final_usage, conversation_id)
			frappe.db.commit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), "AI stream_message save assistant message error")

		# Auto-title on first exchange
		if is_new_conversation:
			try:
				new_title = _auto_title(msg)
				frappe.db.set_value("AI Conversation", conversation_id, "title", new_title)
				frappe.db.commit()
				yield _sse("title_update", {"title": new_title})
			except Exception:
				frappe.log_error(frappe.get_traceback(), "AI stream_message auto-title error")


def _iter_agent_events(agent_run_fn, messages, provider, user, tools):
	"""Yield events from the agent runner one at a time."""
	collected = []

	def on_event(evt):
		collected.append(evt)

	agent_run_fn(
		messages=messages,
		provider=provider,
		user=user,
		stream=True,
		on_event=on_event,
	)

	yield from collected


def _make_response(body) -> Response:
	"""
	Accept either a list (pre-collected chunks) or a generator.
	Werkzeug will iterate it inside ClosingIterator, keeping frappe.local alive.
	"""
	def _iter(data):
		yield from data

	return Response(
		_iter(body),
		content_type="text/event-stream",
		headers={
			"Cache-Control": "no-cache",
			"X-Accel-Buffering": "no",
			"Connection": "keep-alive",
		},
	)


def _save_usage_log(user: str, settings: dict, usage: dict, conversation_id: str):
	try:
		doc = frappe.new_doc("AI Usage Log")
		doc.user = user
		doc.log_date = frappe.utils.today()
		doc.provider = settings.get("provider", "")
		doc.model = settings.get("model", "")
		doc.input_tokens = usage.get("input_tokens", 0)
		doc.output_tokens = usage.get("output_tokens", 0)
		doc.cost_usd = 0.0
		doc.conversation = conversation_id
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "AI usage log save error")


@frappe.whitelist()
def abort_stream(conversation_id: str):
	if not conversation_id:
		frappe.throw("conversation_id is required.")

	user = frappe.session.user
	key = _abort_key(user, conversation_id)
	frappe.cache().set_value(key, 1, expires_in_sec=30)

	return {"status": "ok"}
