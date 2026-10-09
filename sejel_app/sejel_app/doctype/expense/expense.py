import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today


class Expense(Document):
	def validate(self):
		self.set_expense_date()
		self.bind_to_day_close_shift()
		self.check_backdating_permission()

	def set_expense_date(self):
		"""The DAY the expense belongs to. Defaults to today."""
		if not self.expense_date:
			self.expense_date = getdate(today())
		else:
			self.expense_date = getdate(self.expense_date)

	def bind_to_day_close_shift(self):
		"""Attach the expense to the day-close shift of its own date.

		The reconciliation reads a shift's cash expenses through the `shift`
		link and only fell back to `DATE(creation) = shift.date`. Entering an
		expense today for a backdated day therefore left that day's
		total_expenses at 0 with no warning (browser acceptance test
		2026-10-09).
		"""
		if not self.station or not self.expense_date:
			return
		shift = frappe.db.get_value(
			"Shift",
			{"station": self.station, "is_day_close": 1, "date": self.expense_date},
			"name",
		)
		if shift:
			self.shift = shift

	def check_backdating_permission(self):
		"""Only a manager/admin records an expense for a day that has passed.

		Everyone else records today's expenses; letting a supervisor write into
		a closed day's cash position is not something the day-close seal is
		meant to survive.
		"""
		if getdate(self.expense_date) >= getdate(today()):
			return
		roles = set(frappe.get_roles(frappe.session.user))
		if roles & {"System Manager", "Sejel Manager"}:
			return
		frappe.throw(
			_(
				"لا يمكن تسجيل مصروف ليوم سابق — اسأل مدير المحطة لتسجيل مصروف {0}"
			).format(self.expense_date),
			frappe.PermissionError,
		)

	def on_update(self):
		self._refresh_reconciliation()

	def _refresh_reconciliation(self):
		# Same rule as meter readings: a closed day's financial record follows
		# its operational rows. Cash-only expenses are the ones that move
		# net_cash (shift.py `_cash_expenses`).
		if not self.shift or self.payment_method != "cash":
			return
		if self.status not in ("pending", "approved"):
			return
		if not frappe.db.exists("Reconciliation", {"shift": self.shift}):
			return
		frappe.get_doc("Shift", self.shift).refresh_reconciliation()
