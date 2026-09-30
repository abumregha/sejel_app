import frappe
from frappe.model.document import Document


class Reconciliation(Document):
	def recalculate_totals(self):
		fuel_data = frappe.get_all(
			"Shift Fuel Summary",
			filters={"reconciliation": self.name},
			fields=["liters_sold", "expected_sales"],
		)

		self.total_liters = sum(f.liters_sold or 0 for f in fuel_data)
		self.expected_sales = sum(f.expected_sales or 0 for f in fuel_data)

		self.total_cash = frappe.db.sql(
			"""SELECT COALESCE(SUM(amount), 0) FROM `tabCash Collection`
			WHERE shift = %s AND docstatus = 1 AND is_cancelled = 0""",
			self.shift,
		)[0][0]

		self.total_vouchers = frappe.db.sql(
			"""SELECT COALESCE(SUM(total_value), 0) FROM `tabVoucher`
			WHERE shift = %s AND docstatus = 1 AND is_cancelled = 0""",
			self.shift,
		)[0][0]

		self.total_pos = frappe.db.sql(
			"""SELECT COALESCE(SUM(total_amount), 0) FROM `tabPOS Record`
			WHERE shift = %s AND docstatus = 1 AND is_cancelled = 0""",
			self.shift,
		)[0][0]

		self.total_collection = self.total_cash + self.total_vouchers + self.total_pos

		self.total_expenses = frappe.db.sql(
			"""SELECT COALESCE(SUM(amount), 0) FROM `tabExpense`
			WHERE shift = %s AND payment_method = 'cash' AND status IN ('pending', 'approved')
			AND docstatus = 1""",
			self.shift,
		)[0][0]

		self.net_cash = self.total_cash - self.total_expenses
		self.difference = self.total_collection - self.expected_sales
		self.difference_type = (
			"matched" if self.difference == 0
			else "surplus" if self.difference > 0
			else "shortage"
		)
		self.save()
