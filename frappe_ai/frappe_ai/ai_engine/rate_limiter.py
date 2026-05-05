import frappe

from frappe_ai.frappe_ai.ai_engine.base_provider import ProviderRateLimitError


def check_and_increment(user: str, settings: dict) -> None:
	limit = int(settings.get("rate_limit_per_user", 60))
	window_start_cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-1)

	savepoint = f"ai_rate_limit_{user}"
	frappe.db.savepoint(savepoint)

	try:
		existing = frappe.db.get_value(
			"AI Rate Limit",
			filters={
				"user": user,
				"window_start": [">=", window_start_cutoff],
			},
			fieldname=["name", "request_count", "window_start"],
			as_dict=True,
		)

		if existing:
			if existing["request_count"] >= limit:
				reset_at = frappe.utils.add_to_date(existing["window_start"], hours=1)
				now = frappe.utils.now_datetime()
				retry_after = max(0, int((reset_at - now).total_seconds()))
				raise ProviderRateLimitError(
					f"Rate limit exceeded. You may retry in {retry_after} seconds.",
					retry_after=retry_after,
				)

			frappe.db.set_value(
				"AI Rate Limit",
				existing["name"],
				"request_count",
				existing["request_count"] + 1,
			)
		else:
			doc = frappe.new_doc("AI Rate Limit")
			doc.user = user
			doc.window_start = frappe.utils.now()
			doc.request_count = 1
			doc.token_count = 0
			doc.insert(ignore_permissions=True)

		frappe.db.release_savepoint(savepoint)

	except ProviderRateLimitError:
		frappe.db.rollback(save_point=savepoint)
		raise
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		frappe.log_error(frappe.get_traceback(), "rate_limiter.check_and_increment error")


def reset_daily_usage():
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-25)
	frappe.db.delete("AI Rate Limit", {"window_start": ["<", cutoff]})
	frappe.db.commit()


def clean_expired_records():
	cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-2)
	frappe.db.delete("AI Rate Limit", {"window_start": ["<", cutoff]})
	frappe.db.commit()
