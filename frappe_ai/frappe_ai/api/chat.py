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
	All frappe.local usage happens synchronously here before returning the Response.
	The generator only iterates over pre-built SSE strings — no frappe context needed.
	"""
	sse_chunks = []

	try:
		# 1. Input validation
		if not conversation_id:
			sse_chunks.append(_sse("error", {"code": "invalid_input", "message": "conversation_id is required."}))
			return _make_response(sse_chunks)

		msg = (message or "").strip()
		if not msg:
			sse_chunks.append(_sse("error", {"code": "invalid_input", "message": "Message cannot be blank."}))
			return _make_response(sse_chunks)

		if len(msg) > 32000:
			sse_chunks.append(_sse("error", {"code": "invalid_input", "message": "Message too long (max 32,000 characters)."}))
			return _make_response(sse_chunks)

		user = frappe.session.user
		conv_doc = _require_conversation(conversation_id, user)

		attach = attachment
		if attach:
			if not frappe.db.exists("File", {"name": attach, "attached_to_name": user}):
				attach = None

		# 2. Load settings + rate limit
		from frappe_ai.frappe_ai.ai_engine.rate_limiter import check_and_increment
		from frappe_ai.frappe_ai.ai_engine.router import get_provider, get_settings

		settings = get_settings()
		check_and_increment(user, settings)
		provider = get_provider(settings)

		# 3. Save user message
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

		# 4. Build context
		from frappe_ai.frappe_ai.ai_engine.context_manager import build_context

		context_messages = build_context(conversation_id, msg, user, settings)

		# 5. Tools
		tools = []
		if settings.get("tool_calling_enabled"):
			from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import get_tools_for_llm

			tools = get_tools_for_llm(user)

		# 6. Run agent — collect all events synchronously
		from frappe_ai.frappe_ai.ai_engine.agents.agent_runner import run as agent_run

		collected_events = []

		def on_event(evt):
			collected_events.append(evt)

		agent_run(
			messages=context_messages,
			provider=provider,
			user=user,
			stream=True,
			on_event=on_event,
		)

		# 7. Check abort flag (set before we ran — edge case)
		aborted = bool(frappe.cache().get_value(_abort_key(user, conversation_id)))

		full_text = ""
		final_usage = {"input_tokens": 0, "output_tokens": 0}

		for evt in collected_events:
			if aborted:
				break

			event_type = evt.get("event")
			data = evt.get("data", {})

			if event_type == "token":
				delta = data.get("delta", "")
				full_text += delta
				sse_chunks.append(_sse("token", {"delta": delta}))

			elif event_type == "tool_start":
				sse_chunks.append(_sse("tool_start", {"tool": data.get("tool", ""), "args": data.get("args", {})}))

			elif event_type == "tool_result":
				sse_chunks.append(_sse("tool_result", {"tool": data.get("tool", ""), "result": data.get("result", {})}))

			elif event_type == "done":
				usage = data.get("usage", {})
				final_usage["input_tokens"] = usage.get("input", 0)
				final_usage["output_tokens"] = usage.get("output", 0)
				sse_chunks.append(_sse(
					"done",
					{
						"finish_reason": data.get("finish_reason", "stop"),
						"usage": {"input": final_usage["input_tokens"], "output": final_usage["output_tokens"]},
					},
				))

			elif event_type == "error":
				err_msg = data.get("message", "")
				err_code = data.get("code", "provider_error")
				frappe.log_error(
					f"Provider error during stream\nCode: {err_code}\nMessage: {err_msg}",
					"AI stream_message provider event error",
				)
				sse_chunks.append(_sse("error", {"code": err_code, "message": err_msg}))

		# 8. Persist assistant message
		if not aborted:
			conv_doc.reload()
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
			conv_doc.save(ignore_permissions=False)
			_save_usage_log(user, settings, final_usage, conversation_id)
			frappe.db.commit()

		# 9. Auto-title on first exchange
		if conv_doc.title == "New Conversation" and not aborted:
			new_title = _auto_title(msg)
			frappe.db.set_value("AI Conversation", conversation_id, "title", new_title)
			frappe.db.commit()
			sse_chunks.append(_sse("title_update", {"title": new_title}))

	except ProviderRateLimitError as exc:
		retry_after = getattr(exc, "retry_after", None)
		user_msg = str(exc)
		if retry_after:
			user_msg = f"{user_msg} Retry in {retry_after}s."
		sse_chunks.append(_sse(
			"error",
			{"code": "rate_limit", "message": user_msg, "retry_after": retry_after},
		))
	except ProviderAuthError as exc:
		frappe.log_error(frappe.get_traceback(), "AI stream_message auth error")
		sse_chunks.append(_sse("error", {"code": "auth_error", "message": "Invalid API key. Please check AI Assistant Settings."}))
	except ProviderError as exc:
		frappe.log_error(frappe.get_traceback(), "AI stream_message provider error")
		sse_chunks.append(_sse("error", {"code": "provider_error", "message": str(exc)}))
	except Exception:
		frappe.log_error(frappe.get_traceback(), "AI stream_message unexpected error")
		sse_chunks.append(_sse("error", {"code": "server_error", "message": "Unexpected error. Please try again."}))

	return _make_response(sse_chunks)


def _make_response(chunks: list) -> Response:
	body = "".join(chunks)
	return Response(
		body,
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
