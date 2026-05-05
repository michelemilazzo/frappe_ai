import frappe

DEFAULT_SYSTEM_PROMPT = """You are Frappe AI, an intelligent assistant embedded in the Frappe/ERPNext platform. You help users understand their business data, navigate the system, and get things done faster.

You have access to tools that let you search documents, retrieve records, count records, inspect DocType metadata, and — when write tools are available — create, update, and delete records. All actions are scoped strictly to the logged-in user's permissions.

When creating documents: use get_doctype_meta first to discover required fields, then call create_document. Always share the document link from the tool result so the user can view it immediately.

When updating documents: confirm which record to change, then call update_document with only the fields that need to change.

When deleting documents: always confirm with the user before calling delete_document, as this action is irreversible.

Be concise, accurate, and helpful. When presenting data, use tables or bullet points for clarity. When you don't know something or can't access data, say so clearly."""


def after_install():
	_create_ai_user_role()
	_create_default_settings()
	frappe.db.commit()
	frappe.logger().info("Frappe AI installed successfully.")


def before_uninstall():
	_delete_all_records()
	frappe.db.commit()
	frappe.logger().info("Frappe AI uninstalled.")


def _create_ai_user_role():
	if frappe.db.exists("Role", "AI User"):
		return
	role = frappe.new_doc("Role")
	role.role_name = "AI User"
	role.desk_access = 0
	role.insert(ignore_permissions=True)


def _create_default_settings():
	if frappe.db.exists("AI Assistant Settings", "AI Assistant Settings"):
		return
	doc = frappe.new_doc("AI Assistant Settings")
	doc.provider = "Gemini"
	doc.model = "gemini-2.0-flash"
	doc.streaming_enabled = 1
	doc.tool_calling_enabled = 1
	doc.allow_write_tools = 0
	doc.file_upload_enabled = 1
	doc.allowed_file_types = ".pdf,.png,.jpg,.jpeg,.xlsx,.csv"
	doc.max_file_size_mb = 10
	doc.max_tokens = 8192
	doc.temperature = 0.7
	doc.rate_limit_per_user = 60
	doc.monthly_budget_usd = 0
	doc.audit_log_retention_days = 90
	doc.default_system_prompt = DEFAULT_SYSTEM_PROMPT
	doc.insert(ignore_permissions=True)


def _delete_all_records():
	for doctype in [
		"AI Tool Call Log",
		"AI Usage Log",
		"AI Rate Limit",
		"AI Conversation",
	]:
		frappe.db.delete(doctype)

	if frappe.db.exists("AI Assistant Settings", "AI Assistant Settings"):
		frappe.delete_doc("AI Assistant Settings", "AI Assistant Settings", ignore_permissions=True)
