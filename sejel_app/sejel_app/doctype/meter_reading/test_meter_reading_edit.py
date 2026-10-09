import frappe
from frappe.tests.utils import FrappeTestCase


class TestMeterReadingEdit(FrappeTestCase):
	"""Editing an older row must not rewind the meter's counter (QA: fix-readings)."""

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
			 "fuel_type": self.fuel.name, "tank": self.tank.name, "current_reading": 0}
		).insert(ignore_permissions=True)

	def _shift(self, name):
		return frappe.get_doc(
			{"doctype": "Shift", "shift_name": name, "station": self.station.name,
			 "date": frappe.utils.today(), "is_day_close": 1,
			 "start_time": "06:00", "end_time": "14:00"}
		).insert(ignore_permissions=True)

	def _reading(self, shift, start, end, recorded_at=None):
		reading = frappe.get_doc(
			{"doctype": "Meter Reading", "shift": shift.name, "meter": self.meter.name,
			 "start_reading": start, "end_reading": end}
		)
		if recorded_at:
			reading.recorded_at = recorded_at
		reading.insert(ignore_permissions=True)
		return reading

	def _db_counter(self):
		return frappe.db.get_value("Meter", self.meter.name, "current_reading")

	def test_editing_older_row_keeps_latest_counter(self):
		day1 = self._shift("مناوبة QA يوم 1")
		day2 = self._shift("مناوبة QA يوم 2")
		old = self._reading(day1, 100, 200, recorded_at="2026-10-01 23:00:00")
		new = self._reading(day2, 200, 300, recorded_at="2026-10-02 23:00:00")
		self.assertEqual(self._db_counter(), 300)

		# the end user fixes yesterday's typo on the old row. Continuity checks
		# against the newest other reading, so correcting an older row always
		# carries a documented reason (exception_type + notes).
		old.reload()
		old.end_reading = 250
		old.exception_type = "other"
		old.notes = "تصحيح خطأ إدخال"
		old.save()
		# the meter's counter must still reflect the LATEST reading (300)
		self.assertEqual(self._db_counter(), 300)
		self.assertEqual(
			frappe.db.get_value("Meter Reading", new.name, "end_reading"), 300
		)

	def test_start_only_row_leaves_seeded_counter(self):
		shift = self._shift("مناوبة QA بدون إغلاق")
		# counter established by an operator/QA seeding; the reading has no end
		frappe.db.set_value("Meter", self.meter.name, "current_reading", 4242)
		self._reading(shift, 4242, None)
		self.assertEqual(self._db_counter(), 4242)
