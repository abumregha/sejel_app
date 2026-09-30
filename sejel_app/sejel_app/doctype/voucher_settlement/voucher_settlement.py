import frappe
from frappe.model.document import Document


class VoucherSettlement(Document):
	def validate(self):
		self.calculate_totals()

	def calculate_totals(self):
		self.total_value = (
			(self.denom_5 or 0) * 5
			+ (self.denom_6 or 0) * 6
			+ (self.denom_7 or 0) * 7
			+ (self.denom_8 or 0) * 8
		)
		self.total_count = (self.denom_5 or 0) + (self.denom_6 or 0) + (self.denom_7 or 0) + (self.denom_8 or 0)

	@property
	def outstanding(self):
		return self.total_value - self.paid_amount
