import frappe
from frappe.model.document import Document


class Delivery(Document):
	def validate(self):
		self.calculate_shortage()

	def calculate_shortage(self):
		if self.pre_reading is not None and self.post_reading is not None:
			self.received_quantity = self.post_reading - self.pre_reading
			expected = self.expected_quantity if self.expected_quantity is not None else 0
			self.shortage = max(0, expected - self.received_quantity)
			if self.received_quantity > 0:
				self.status = "received"
		elif self.received_quantity is None:
			self.received_quantity = 0
		if self.shortage is None:
			self.shortage = 0
		return self.shortage
