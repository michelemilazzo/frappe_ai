import frappe
from frappe.model.document import Document


class AIAssistantSettings(Document):
	def validate(self):
		if self.temperature is not None and not (0.0 <= self.temperature <= 2.0):
			frappe.throw("Temperature must be between 0.0 and 2.0")
		if self.max_tokens is not None and self.max_tokens < 1:
			frappe.throw("Max Tokens must be at least 1")
