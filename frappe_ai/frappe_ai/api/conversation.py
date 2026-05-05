import re

import frappe


def _require_owner(conversation_id: str) -> object:
	doc = frappe.get_doc("AI Conversation", conversation_id)
	if doc.owner != frappe.session.user and "System Manager" not in frappe.get_roles(frappe.session.user):
		frappe.throw("Access denied.", frappe.PermissionError)
	return doc


@frappe.whitelist()
def list(page=0, limit=20):
	user = frappe.session.user
	page = int(page or 0)
	limit = min(int(limit or 20), 100)

	conversations = frappe.get_list(
		"AI Conversation",
		filters={"owner": user, "is_archived": 0},
		fields=[
			"name",
			"title",
			"model_used",
			"provider_used",
			"modified",
			"is_pinned",
			"total_input_tokens",
			"total_output_tokens",
		],
		order_by="is_pinned desc, modified desc",
		limit=limit,
		start=page * limit,
		ignore_permissions=False,
	)

	# Attach the last assistant message content as a snippet for each conversation
	if conversations:
		names = [c.name for c in conversations]
		placeholders = ", ".join(["%s"] * len(names))
		rows = frappe.db.sql(
			f"""
			SELECT m.parent, m.content
			FROM `tabAI Message` m
			INNER JOIN (
				SELECT parent, MAX(idx) AS max_idx
				FROM `tabAI Message`
				WHERE parent IN ({placeholders}) AND role = 'assistant'
				GROUP BY parent
			) latest ON m.parent = latest.parent AND m.idx = latest.max_idx
			""",
			tuple(names),
			as_dict=True,
		)
		snippet_map = {r.parent: r.content for r in rows}
		for c in conversations:
			raw = snippet_map.get(c.name, "")
			c["last_message"] = (raw[:80] + "…") if len(raw) > 80 else raw

	total = frappe.db.count("AI Conversation", {"owner": user, "is_archived": 0})

	return {"conversations": conversations, "total": total}


@frappe.whitelist()
def get(conversation_id: str):
	if not conversation_id:
		frappe.throw("conversation_id is required.")

	doc = _require_owner(conversation_id)
	return {"conversation": doc.as_dict()}


@frappe.whitelist()
def create():
	from frappe_ai.frappe_ai.ai_engine.router import get_settings

	settings = get_settings()

	doc = frappe.new_doc("AI Conversation")
	doc.owner = frappe.session.user
	doc.model_used = settings.get("model", "gemini-2.0-flash")
	doc.provider_used = settings.get("provider", "Gemini")
	doc.title = "New Conversation"
	doc.insert(ignore_permissions=False)
	frappe.db.commit()

	return {"conversation_id": doc.name, "title": doc.title}


@frappe.whitelist()
def delete(conversation_id: str):
	if not conversation_id:
		frappe.throw("conversation_id is required.")

	doc = _require_owner(conversation_id)
	doc.is_archived = 1
	doc.save(ignore_permissions=False)
	frappe.db.commit()

	return {"status": "ok"}


@frappe.whitelist()
def update_title(conversation_id: str, title: str):
	if not conversation_id:
		frappe.throw("conversation_id is required.")
	if not title or not title.strip():
		frappe.throw("title cannot be blank.")

	clean_title = re.sub(r"<[^>]+>", "", title).strip()[:120]
	doc = _require_owner(conversation_id)
	doc.title = clean_title
	doc.save(ignore_permissions=False)
	frappe.db.commit()

	return {"status": "ok", "title": clean_title}
