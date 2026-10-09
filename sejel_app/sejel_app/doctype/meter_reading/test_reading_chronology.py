import frappe
from frappe.tests.utils import FrappeTestCase


class TestReadingChronology(FrappeTestCase):
	"""A reading belongs to a DAY (its shift), not to the moment it was typed.

	Entering yesterday and the day before today in one sitting — the customer
	does exactly this — gives every row the SAME recorded_at (the entry clock).
	Ordering chains by recorded_at is then arbitrary, so the predecessor /
	successor checks of validate_continuity and the counter recompute follow the
	wrong row.
	"""

	def setUp(self):
		suffix = frappe.utils.random_string(5)
		self.fuel = frappe.get_doc(
			{"doctype": "Fuel Type", "fuel_name": "بنزين QA " + suffix}
		).insert(ignore_permissions=True)
		self.station = frappe.get_doc(
			{"doctype": "Station", "station_name": "محطة QA " + suffix}
		).insert(ignore_permissions=True)
		self.island = frappe.get_doc(
			{"doctype": "Island", "island_name": "جزيرة QA", "station": self.station.name, "number": 1}
		).insert(ignore_permissions=True)
		self.machine = frappe.get_doc(
			{"doctype": "Machine", "machine_name": "مضخة QA", "island": self.island.name,
			 "station": self.station.name, "number": 1}
		).insert(ignore_permissions=True)
		self.tank = frappe.get_doc(
			{"doctype": "Tank", "tank_name": "خزان QA", "station": self.station.name,
			 "fuel_type": self.fuel.name, "capacity": 10000}
		).insert(ignore_permissions=True)
		self.meter = frappe.get_doc(
			{"doctype": "Meter", "meter_code": "QA" + suffix, "machine": self.machine.name,
			 "fuel_type": self.fuel.name, "tank": self.tank.name, "current_reading": 1000}
		).insert(ignore_permissions=True)

	def _shift(self, day):
		return frappe.get_doc(
			{"doctype": "Shift", "shift_name": f"مناوبة QA {day}", "station": self.station.name,
			 "date": day, "is_day_close": 1, "start_time": "06:00", "end_time": "14:00"}
		).insert(ignore_permissions=True)

	def _bulk_enter(self):
		"""Three days typed in ONE sitting — identical entry timestamp, different days."""
		rows = []
		for day, start, end in (
			("2026-10-01", 1000, 2000),
			("2026-10-02", 2000, 3000),
			("2026-10-03", 3000, 4000),
		):
			doc = frappe.get_doc(
				{"doctype": "Meter Reading", "shift": self._shift(day).name,
				 "meter": self.meter.name, "start_reading": start, "end_reading": end}
			)
			doc.recorded_at = "2026-10-09 14:56:13"
			doc.insert(ignore_permissions=True)
			rows.append(doc)
		self.assertEqual(
			len({r.recorded_at for r in rows}), 1, "fixture must share one entry timestamp"
		)
		return rows

	def test_counter_follows_the_latest_DAY_not_the_last_typed_row(self):
		day1, day2, day3 = self._bulk_enter()
		# re-enter the OLDEST day last, so insertion order contradicts chronology
		frappe.db.set_value("Meter Reading", day1.name, "end_reading", 2000)
		self.assertEqual(
			frappe.db.get_value("Meter", self.meter.name, "current_reading"), 4000
		)

	def test_successor_is_found_by_day_when_timestamps_are_shared(self):
		day1, day2, day3 = self._bulk_enter()
		doc = frappe.get_doc("Meter Reading", day1.name)
		before, after = doc._chain_neighbours()
		self.assertIsNone(before, "the first day has no predecessor")
		self.assertIsNotNone(after, "the corrected day must expose its successor")
		self.assertEqual(after.start_reading, 2000)

		doc.end_reading = 2500  # day 2 still starts at 2000
		self.assertRaises(frappe.ValidationError, doc.save)

	def test_a_previous_reason_does_not_authorise_a_later_correction(self):
		day1, day2, day3 = self._bulk_enter()
		doc = frappe.get_doc("Meter Reading", day1.name)
		doc.end_reading = 2000
		doc.exception_type = "other"
		doc.notes = "تصحيح خطأ إدخال"
		doc.save()

		# a NEW correction that breaks the next day must ask for its own reason;
		# the reason from the previous correction is not a pass for this one
		from frappe.utils import cint
		frappe.db.set_value(
			"Meter Reading", day1.name,
			{"exception_type": "", "notes": None, "end_reading": 2000},
		)
		fresh = frappe.get_doc("Meter Reading", day1.name)
		fresh.end_reading = 2500
		self.assertRaises(frappe.ValidationError, fresh.save)
		self.assertFalse(cint(fresh.exception_type), "the stale reason must not survive")
