import frappe
from frappe.model.document import Document


class StationDeposit(Document):
	def validate(self):
		self.calculate_balance()
		self.check_duplicate_invoice()

	def calculate_balance(self):
		deposits = frappe.get_all(
			"Station Deposit",
			filters={"station": self.station, "name": ["!=", self.name]},
			fields=["deposit_amount"],
		)
		total_deposits = sum(float(d.deposit_amount or 0) for d in deposits) + float(self.deposit_amount or 0)

		deductions = frappe.get_all(
			"Stock Entry",
			filters={"station": self.station, "entry_type": ["in", ["delivery", "rent"]], "docstatus": 1},
			fields=["total_amount"],
		)
		total_deductions = sum(float(d.total_amount or 0) for d in deductions)

		self.allocated_amount = total_deductions
		self.balance = total_deposits - total_deductions

	def check_duplicate_invoice(self):
		if not self.invoice_number:
			return
		existing = frappe.db.get_value(
			"Station Deposit",
			{"invoice_number": self.invoice_number, "name": ["!=", self.name]},
			"name",
		)
		if existing:
			frappe.throw("يوجد إيداع بنفس رقم الفاتورة: {}".format(self.invoice_number))
