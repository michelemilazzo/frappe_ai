import json
from datetime import date, datetime
from decimal import Decimal

import frappe

from frappe_ai.frappe_ai.ai_engine.agents.tool_registry import get_handler, get_tools_for_llm
from frappe_ai.frappe_ai.ai_engine.base_provider import ProviderError

MAX_TOOL_ITERATIONS = 8


class _FrappeEncoder(json.JSONEncoder):
	def default(self, o):
		if isinstance(o, datetime):
			return o.isoformat()
		if isinstance(o, date):
			return o.isoformat()
		if isinstance(o, Decimal):
			return float(o)
		try:
			return super().default(o)
		except TypeError:
			return str(o)


def _dumps(obj) -> str:
	return json.dumps(obj, cls=_FrappeEncoder)

_BUDGET_EXCEEDED_MSG = (
	"Monthly usage budget has been reached. Please contact your administrator."
)
_MAX_ITERATIONS_MSG = (
	"I reached the maximum number of tool calls for this request. "
	"Here is what I found so far."
)


def run(messages: list, provider, user: str, stream: bool = False, on_event=None) -> dict:
	_check_budget(user)

	tools = get_tools_for_llm(user) if provider.supports_tools() else []

	if not stream:
		return _run_sync(messages, provider, user, tools)

	return _run_stream(messages, provider, user, tools, on_event)


def _check_budget(user: str):
	from frappe_ai.frappe_ai.ai_engine.router import get_settings

	settings = get_settings()
	budget = settings.get("monthly_budget_usd", 0)
	if not budget:
		return

	from frappe.utils import get_first_day, today

	month_start = get_first_day(today())
	total_cost = (
		frappe.db.get_value(
			"AI Usage Log",
			filters={"user": user, "log_date": [">=", month_start]},
			fieldname="sum(cost_usd)",
		)
		or 0
	)
	if float(total_cost) >= float(budget):
		raise ProviderError(_BUDGET_EXCEEDED_MSG)


def _run_sync(messages: list, provider, user: str, tools: list) -> dict:
	current_messages = list(messages)

	for _iteration in range(MAX_TOOL_ITERATIONS):
		response = provider.chat(current_messages, tools=tools if tools else None)

		if response.get("finish_reason") != "tool_calls" or not response.get("tool_calls"):
			return response

		current_messages.append(
			{
				"role": "assistant",
				"content": response.get("content") or "",
				"tool_calls": response["tool_calls"],
			}
		)

		for call in response["tool_calls"]:
			fn_name = call.get("function", {}).get("name") or call.get("id", "")
			raw_args = call.get("function", {}).get("arguments", "{}")
			try:
				args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
			except json.JSONDecodeError:
				args = {}

			result = _execute_tool(fn_name, args, user)
			current_messages.append(
				{
					"role": "tool",
					"tool_call_id": fn_name,
					"content": _dumps(result),
				}
			)

	# Hard stop
	return {
		"content": _MAX_ITERATIONS_MSG,
		"role": "assistant",
		"tool_calls": None,
		"finish_reason": "stop",
		"usage": {"input_tokens": 0, "output_tokens": 0},
	}


def _run_stream(messages: list, provider, user: str, tools: list, on_event):
	current_messages = list(messages)
	final_response = {
		"content": "",
		"role": "assistant",
		"finish_reason": "stop",
		"usage": {"input_tokens": 0, "output_tokens": 0},
	}

	for _iteration in range(MAX_TOOL_ITERATIONS):
		accumulated_text = ""
		accumulated_tool_calls = []
		done_data = {}

		for event in provider.stream(current_messages, tools=tools if tools else None):
			event_type = event.get("event")

			if on_event:
				on_event(event)

			if event_type == "token":
				accumulated_text += event["data"].get("delta", "")
			elif event_type == "tool_start":
				pass
			elif event_type == "done":
				done_data = event.get("data", {})
				tc = done_data.get("tool_calls")
				if tc:
					accumulated_tool_calls = tc
			elif event_type == "error":
				frappe.log_error(
					f"Provider stream error: {event.get('data', {}).get('message', '')}",
					"AI agent_runner provider error",
				)
				return final_response

		finish_reason = done_data.get("finish_reason", "stop")
		usage = done_data.get("usage", {})
		final_response["content"] = accumulated_text
		final_response["finish_reason"] = finish_reason
		final_response["usage"] = {
			"input_tokens": usage.get("input", 0),
			"output_tokens": usage.get("output", 0),
		}

		if finish_reason != "tool_calls" or not accumulated_tool_calls:
			return final_response

		current_messages.append(
			{
				"role": "assistant",
				"content": accumulated_text,
				"tool_calls": accumulated_tool_calls,
			}
		)

		for call in accumulated_tool_calls:
			fn_name = call.get("function", {}).get("name") or call.get("id", "")
			raw_args = call.get("function", {}).get("arguments", "{}")
			try:
				args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
			except json.JSONDecodeError:
				args = {}

			if on_event:
				on_event({"event": "tool_start", "data": {"tool": fn_name, "args": args}})

			result = _execute_tool(fn_name, args, user)

			if on_event:
				on_event({"event": "tool_result", "data": {"tool": fn_name, "result": result}})

			current_messages.append(
				{
					"role": "tool",
					"tool_call_id": fn_name,
					"content": _dumps(result),
				}
			)

	final_response["content"] = _MAX_ITERATIONS_MSG
	if on_event:
		on_event(
			{
				"event": "done",
				"data": {"finish_reason": "stop", "usage": {"input": 0, "output": 0}},
			}
		)
	return final_response


def _execute_tool(name: str, args: dict, user: str) -> dict:
	try:
		handler = get_handler(name)
		return handler(args, user)
	except KeyError:
		return {"error": f"Unknown tool: {name}"}
	except Exception as exc:
		frappe.log_error(frappe.get_traceback(), f"Tool execution error: {name}")
		return {"error": str(exc)}
