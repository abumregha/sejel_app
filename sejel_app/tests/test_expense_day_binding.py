import frappe
from frappe.tests.utils import FrappeTestCase


class TestExpenseDayBinding(FrappeTestCase):
	"""An expense must belong to the DAY it happened, not to the day it was typed.

	The reconciliation picks a shift's cash expenses by `shift` link and falls
	back to `DATE(creation) = shift.date`, so an expense entered today for a
	backdated day was silently excluded from that day's `total_expenses`
	(browser acceptance test 2026-10-09: two 300 د.ل expenses, recon expenses 0).
	"""

	def setUp(self):
		suffix = frappe.utils.random_string(5)
		self.fuel = frappe.get_doc(
			{"doctype": "Fuel Type", "fuel_name": "بنزين QA " + suffix}
		).insert(ignore_permissions=True)
		self.category = frappe.get_doc(
			{"doctype": "Expense Category", "category_name": "صيانة QA " + suffix, "is_active": 1}
		).insert(ignore_permissions=True)
		self.station = frappe.get_doc(
			{"doctype": "Station", "station_name": "محطة QA " + suffix}
		).insert(ignore_permissions=True)
		self.day_shift = self._shift("2026-10-01")

	def _shift(self, day):
		return frappe.get_doc(
			{"doctype": "Shift", "shift_name": f"مناوبة QA {day}", "station": self.station.name,
			 "date": day, "is_day_close": 1, "start_time": "06:00", "end_time": "14:00"}
		).insert(ignore_permissions=True)

	def _expense(self, day, user="Administrator"):
		frappe.set_user(user)
		try:
			return frappe.get_doc(
				{"doctype": "Expense", "station": self.station.name, "category": self.category.name,
				 "amount": 300, "description": "اختبار", "payment_method": "cash",
				 "expense_date": day}
			).insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def test_expense_links_to_the_day_close_shift_of_its_date(self):
		expense = self._expense("2026-10-01")
		self.assertEqual(expense.shift, self.day_shift.name)
		self.assertEqual(str(expense.expense_date), "2026-10-01")

	def test_a_backdated_expense_counts_towards_that_days_reconciliation(self):
		self._expense("2026-10-01")
		frappe.get_doc(
			{"doctype": "Fuel Price", "fuel_type": self.fuel.name, "selling_price": 2.0,
			 "cost_per_liter": 1.5, "effective_date": "2026-01-01", "is_active": 1}
		).insert(ignore_permissions=True)
		self._reading()
		shift = frappe.get_doc("Shift", self.day_shift.name)
		shift.status = "submitted"
		shift.save()
		shift.close_shift()

		recon = frappe.get_doc("Reconciliation", {"shift": self.day_shift.name})
		self.assertEqual(recon.total_expenses, 300)
		self.assertEqual(recon.net_cash, 0 - 300)

	def test_editing_the_closed_day_expense_refreshes_its_reconciliation(self):
		self._expense("2026-10-01")
		frappe.get_doc(
			{"doctype": "Fuel Price", "fuel_type": self.fuel.name, "selling_price": 2.0,
			 "cost_per_liter": 1.5, "effective_date": "2026-01-01", "is_active": 1}
		).insert(ignore_permissions=True)
		self._reading()
		shift = frappe.get_doc("Shift", self.day_shift.name)
		shift.status = "submitted"
		shift.save()
		shift.close_shift()

		expense = frappe.get_doc(
			"Expense", frappe.get_all("Expense", filters={"station": self.station.name}, pluck="name")[0]
		)
		expense.amount = 500
		expense.save()
		self.assertEqual(
			frappe.db.get_value(
				"Reconciliation", {"shift": self.day_shift.name}, "total_expenses"
			),
			500,
		)

	def _reading(self):
		island = frappe.get_doc(
			{"doctype": "Island", "island_name": "جزيرة QA", "station": self.station.name, "number": 1}
		).insert(ignore_permissions=True)
		machine = frappe.get_doc(
			{"doctype": "Machine", "machine_name": "مضخة QA", "island": island.name,
			 "station": self.station.name, "number": 1}
		).insert(ignore_permissions=True)
		tank = frappe.get_doc(
			{"doctype": "Tank", "tank_name": "خزان QA", "station": self.station.name,
			 "fuel_type": self.fuel.name, "capacity": 10000}
		).insert(ignore_permissions=True)
		meter = frappe.get_doc(
			{"doctype": "Meter", "meter_code": "QA" + frappe.utils.random_string(4),
			 "machine": machine.name, "fuel_type": self.fuel.name, "tank": tank.name,
			 "current_reading": 1000}
		).insert(ignore_permissions=True)
		return frappe.get_doc(
			{"doctype": "Meter Reading", "shift": self.day_shift.name, "meter": meter.name,
			 "start_reading": 1000, "end_reading": 2000}
		).insert(ignore_permissions=True)

	def test_a_supervisor_cannot_backdate_an_expense(self):
		if not frappe.db.exists("User", "qa.supervisor@test.local"):
			frappe.get_doc(
				{"doctype": "User", "email": "qa.supervisor@test.local", "first_name": "QA",
				 "username": "qa.supervisor", "send_welcome_email": 0, "user_type": "System User",
				 "roles": [{"role": "Sejel Supervisor"}]}
			).insert(ignore_permissions=True)
		with self.assertRaises(frappe.PermissionError):
			self._expense("2026-01-01", user="qa.supervisor@test.local")

	def test_a_manager_may_backdate(self):
		if not frappe.db.exists("User", "qa.manager@test.local"):
			frappe.get_doc(
				{"doctype": "User", "email": "qa.manager@test.local", "first_name": "QA",
				 "username": "qa.manager", "send_welcome_email": 0, "user_type": "System User",
				 "roles": [{"role": "Sejel Manager"}]}
			).insert(ignore_permissions=True)
		expense = self._expense("2026-01-01", user="qa.manager@test.local")
		self.assertEqual(str(expense.expense_date), "2026-01-01")
