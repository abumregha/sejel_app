import frappe
from frappe.tests.utils import FrappeTestCase
from sejel_app.api.income import record_income_legs


class TestIncomeEntryIdempotency(FrappeTestCase):
	"""Re-saving an income entry must never duplicate the legs that already posted.

	Reproduced in the browser acceptance test (2026-10-09): the coupons leg
	failed (no coupon category existed), the form said "press save again to
	finish the unsaved leg" — and pressing save again re-posted the legs that
	had already succeeded, leaving two identical Voucher rows and an inflated
	total_vouchers on that day's reconciliation.
	"""

	def setUp(self):
		suffix = frappe.utils.random_string(5)
		self.fuel = frappe.get_doc(
			{"doctype": "Fuel Type", "fuel_name": "بنزين QA " + suffix}
		).insert(ignore_permissions=True)
		self.station = frappe.get_doc(
			{"doctype": "Station", "station_name": "محطة QA " + suffix}
		).insert(ignore_permissions=True)
		self.shift = frappe.get_doc(
			{"doctype": "Shift", "shift_name": f"مناوبة QA {suffix}",
			 "station": self.station.name, "date": "2026-10-01", "is_day_close": 1,
			 "start_time": "06:00", "end_time": "14:00"}
		).insert(ignore_permissions=True)
		self.missing_category = "فئة كوبونات غير موجودة"

	def _leg_counts(self):
		return (
			frappe.db.count("Cash Collection", {"shift": self.shift.name}),
			frappe.db.count("Voucher", {"shift": self.shift.name}),
			frappe.db.count("POS Record", {"shift": self.shift.name}),
		)

	def _entry(self, request_id, coupons):
		return record_income_legs(
			shift=self.shift.name,
			cash_amount=5000,
			coupon_legs=coupons,
			epayment_amount=200,
			epayment_count=2,
			request_id=request_id,
		)

	def test_retry_after_a_partial_failure_does_not_duplicate(self):
		broken = [{"category": self.missing_category, "count": 100, "value": 5}]

		# 1st save: cash + e-payment succeed, the coupons leg fails on purpose
		first = self._entry("R1", broken)
		self.assertFalse(first["ok"])
		self.assertEqual(len(first["failed"]), 1)
		self.assertEqual(self._leg_counts(), (1, 0, 1))

		# 2nd save, SAME request id — the operator pressed save again while the
		# coupons leg is still broken
		second = self._entry("R1", broken)
		self.assertFalse(second["ok"])
		self.assertEqual(self._leg_counts(), (1, 0, 1), "already-saved legs were duplicated")

		# 3rd save: the category now exists, so the missing leg completes — and
		# only that leg is created
		frappe.get_doc(
			{"doctype": "Voucher Category", "category_name": "5 د.ل QA", "value": 5, "is_active": 1}
		).insert(ignore_permissions=True)
		category = frappe.get_all("Voucher Category", filters={"category_name": "5 د.ل QA"}, pluck="name")[0]
		third = self._entry("R1", [{"category": category, "count": 100, "value": 5}])
		self.assertTrue(third["ok"])
		self.assertEqual(self._leg_counts(), (1, 1, 1))
		self.assertEqual(
			frappe.db.get_value("Voucher", {"shift": self.shift.name}, "total_value"), 500.0
		)

	def test_a_second_entry_for_the_same_day_is_not_swallowed(self):
		good = []
		first = self._entry("R-A", good)
		self.assertTrue(first["ok"])
		self.assertEqual(self._leg_counts(), (1, 0, 1))

		# a genuinely different entry (new request id) posts its own rows
		second = self._entry("R-B", good)
		self.assertTrue(second["ok"])
		self.assertEqual(self._leg_counts(), (2, 0, 2))

	def test_response_reports_every_leg(self):
		result = self._entry("R-C", [])
		self.assertEqual(result["request_id"], "R-C")
		self.assertEqual({leg["leg"] for leg in result["legs"]}, {"cash", "epayment"})
		self.assertTrue(all(leg["ok"] for leg in result["legs"]))
