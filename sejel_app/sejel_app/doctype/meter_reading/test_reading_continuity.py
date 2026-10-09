import frappe
from frappe.tests.utils import FrappeTestCase


class TestReadingContinuityChain(FrappeTestCase):
	"""A reading must continue its own PREDECESSOR, and a correction must not
	silently break the day that follows it.

	Before: continuity compared `start_reading` against the NEWEST other
	reading for the meter, so correcting any older day demanded an exception for
	a "gap" that did not exist, and nothing ever checked the other direction — a
	correction that changed a day's end left the next day's start silently
	mismatched (browser acceptance test, 2026-10-09).
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

	def _reading(self, day, start, end):
		shift = frappe.get_doc(
			{"doctype": "Shift", "shift_name": f"مناوبة QA {day}", "station": self.station.name,
			 "date": day, "is_day_close": 1, "start_time": "06:00", "end_time": "14:00"}
		).insert(ignore_permissions=True)
		doc = frappe.get_doc(
			{"doctype": "Meter Reading", "shift": shift.name, "meter": self.meter.name,
			 "start_reading": start, "end_reading": end}
		)
		doc.recorded_at = f"{day} 23:00:00"
		doc.insert(ignore_permissions=True)
		return doc

	def _three_days(self):
		return (
			self._reading("2026-10-01", 1000, 2000),
			self._reading("2026-10-02", 2000, 3000),
			self._reading("2026-10-03", 3000, 4000),
		)

	def test_older_day_start_continues_its_own_predecessor(self):
		day1, day2, day3 = self._three_days()
		# day1 has no predecessor: its start is whatever the counter said
		day1.reload()
		day1.start_reading = 1200
		day1.end_reading = 2000
		day1.save()  # no exception needed — nothing before day1 to contradict

	def test_editing_older_day_end_that_breaks_the_next_day_needs_a_reason(self):
		day1, day2, day3 = self._three_days()
		day1.reload()
		day1.end_reading = 2500  # day2 still starts at 2000 → the chain now breaks
		self.assertRaises(frappe.ValidationError, day1.save)

		day1.reload()
		day1.end_reading = 2500
		day1.exception_type = "other"
		day1.notes = "تصحيح خطأ إدخال"
		day1.save()

		# the later day is NOT silently altered — that is the operator's call
		day2.reload()
		self.assertEqual(day2.start_reading, 2000)

	def test_editing_the_latest_day_never_needs_a_successor_reason(self):
		day1, day2, day3 = self._three_days()
		day3.reload()
		day3.end_reading = 4500
		day3.save()  # nothing follows it
		self.assertEqual(
			frappe.db.get_value("Meter Reading", day3.name, "end_reading"), 4500
		)

	def test_out_of_order_entry_still_needs_a_reason(self):
		# today's reading exists first; yesterday is entered afterwards with a
		# start that does not continue today's end → gap protection preserved
		self._reading("2026-10-02", 2000, 3000)
		late = frappe.get_doc(
			{"doctype": "Meter Reading", "meter": self.meter.name, "start_reading": 500,
			 "end_reading": 1500}
		)
		shift = frappe.get_all("Shift", filters={"station": self.station.name}, pluck="name")[0]
		late.shift = shift
		late.recorded_at = "2026-10-01 23:00:00"
		self.assertRaises(frappe.ValidationError, late.insert)
