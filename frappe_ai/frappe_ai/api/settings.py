import frappe


@frappe.whitelist()
def get_public():
	doc = frappe.get_single("AI Assistant Settings")
	return {
		"provider": doc.provider,
		"model": doc.model,
		"streaming_enabled": bool(doc.streaming_enabled),
		"tool_calling_enabled": bool(doc.tool_calling_enabled),
		"file_upload_enabled": bool(doc.file_upload_enabled),
		"allowed_file_types": doc.allowed_file_types or ".pdf,.png,.jpg,.jpeg,.xlsx,.csv",
		"max_file_size_mb": doc.max_file_size_mb or 10,
	}


@frappe.whitelist(allow_guest=False)
def test_connection():
	if not frappe.has_permission("AI Assistant Settings", "write"):
		frappe.throw("Only System Managers can test the connection.", frappe.PermissionError)

	try:
		from frappe_ai.frappe_ai.ai_engine.router import get_provider, get_settings

		settings = get_settings()
		provider = get_provider(settings)
		provider.count_tokens([{"role": "user", "content": "test"}])

		return {"status": "ok", "model": settings.get("model"), "provider": settings.get("provider")}
	except Exception as exc:
		return {"status": "error", "message": str(exc)}


@frappe.whitelist()
def get_usage(period: str = "month"):
	user = frappe.session.user

	today = frappe.utils.today()
	if period == "today":
		date_filter = today
		filters = {"user": user, "log_date": today}
	elif period == "week":
		week_start = frappe.utils.add_to_date(today, days=-7)
		filters = {"user": user, "log_date": [">=", week_start]}
	else:
		month_start = frappe.utils.get_first_day(today)
		filters = {"user": user, "log_date": [">=", month_start]}

	logs = frappe.get_list(
		"AI Usage Log",
		filters=filters,
		fields=["input_tokens", "output_tokens", "cost_usd"],
		ignore_permissions=False,
	)

	total_input = sum(r.get("input_tokens") or 0 for r in logs)
	total_output = sum(r.get("output_tokens") or 0 for r in logs)
	total_cost = sum(float(r.get("cost_usd") or 0) for r in logs)

	return {
		"input_tokens": total_input,
		"output_tokens": total_output,
		"total_tokens": total_input + total_output,
		"cost_usd": round(total_cost, 6),
		"request_count": len(logs),
		"period": period,
	}
