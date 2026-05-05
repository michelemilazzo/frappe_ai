import frappe
from frappe.model.document import Document


def get_permission_query_conditions(user=None):
	if not user:
		user = frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return ""
	return f"(`tabAI Conversation`.`owner` = {frappe.db.escape(user)})"


class AIConversation(Document):
	def validate(self):
		if self.title and len(self.title) > 120:
			self.title = self.title[:120]
