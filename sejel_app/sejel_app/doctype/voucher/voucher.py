import frappe
from frappe.model.document import Document


class Voucher(Document):
	def validate(self):
		if self.category and not self.total_value:
			price = frappe.db.get_value("Voucher Category", self.category, "value")
			if price:
				self.total_value = self.count * price
