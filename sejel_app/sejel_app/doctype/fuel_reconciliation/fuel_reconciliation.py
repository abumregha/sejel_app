import frappe
from frappe.model.document import Document


class FuelReconciliation(Document):
	def validate(self):
		self.calculate_theoretical()

	def calculate_theoretical(self):
		base = 0
		if self.opening_reading:
			base = frappe.db.get_value("Tank Reading", self.opening_reading, "reading_level") or 0

		self.theoretical_level = (
			base
			+ (self.received_quantity or 0)
			+ (self.transferred_in or 0)
			- (self.transferred_out or 0)
			- (self.sold_quantity or 0)
		)
		self.variance = (self.actual_level or 0) - self.theoretical_level
		self.variance_type = (
			"matched" if self.variance == 0
			else "surplus" if self.variance > 0
			else "shortage"
		)
