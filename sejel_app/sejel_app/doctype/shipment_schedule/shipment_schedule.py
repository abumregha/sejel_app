import frappe
from frappe.model.document import Document


class ShipmentSchedule(Document):
	def validate(self):
		self.calculate_total()
		self.sync_invoice_number()

	def calculate_total(self):
		qty = float(self.quantity or 0)
		price = float(self.unit_price or 0)
		self.total_amount = qty * price

	def sync_invoice_number(self):
		if self.deposit:
			dep = frappe.get_doc("Station Deposit", self.deposit)
			self.invoice_number = dep.invoice_number
			self.station = dep.station
