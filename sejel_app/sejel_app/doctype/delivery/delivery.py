import frappe
from frappe.model.document import Document


class Delivery(Document):
	def validate(self):
		self.calculate_shortage()
		self.validate_delivery_status()

	def calculate_shortage(self):
		if self.pre_reading is not None and self.post_reading is not None:
			self.received_quantity = self.post_reading - self.pre_reading
			expected = self.expected_quantity if self.expected_quantity is not None else 0
			self.shortage = max(0, expected - self.received_quantity)
			if self.received_quantity > 0 and self.status not in ("undelivered", "transit"):
				self.status = "received"
		elif self.received_quantity is None:
			self.received_quantity = 0
		if self.shortage is None:
			self.shortage = 0
		return self.shortage

	def validate_delivery_status(self):
		if self.status == "undelivered":
			self.received_quantity = 0
			self.shortage = self.expected_quantity or 0
			self.arrival_date = None
		elif self.status == "transit":
			self.arrival_date = None
		elif self.status == "received" and self.scheduled_date and not self.arrival_date:
			self.arrival_date = frappe.utils.now_datetime()
