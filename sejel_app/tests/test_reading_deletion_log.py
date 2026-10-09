import frappe
from frappe.tests.utils import FrappeTestCase


class TestReadingDeletionLog(FrappeTestCase):
	"""Deleting a reading must leave a permanent trace.

	Frappe removes a document's `Version` rows along with it
	(`frappe/model/delete_doc.py` → `delete_references("Version", …)`), so after
	a delete there was nothing left to answer "who removed this reading and what
	did it say?" (browser acceptance test 2026-10-09).
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
		self.shift = frappe.get_doc(
			{"doctype": "Shift", "shift_name": f"مناوبة QA {suffix}", "station": self.station.name,
			 "date": "2026-10-01", "is_day_close": 1, "start_time": "06:00", "end_time": "14:00"}
		).insert(ignore_permissions=True)

	def _reading(self, start=1000, end=2000, exception_type="", notes=None):
		return frappe.get_doc(
			{"doctype": "Meter Reading", "shift": self.shift.name, "meter": self.meter.name,
			 "start_reading": start, "end_reading": end,
			 "exception_type": exception_type, "notes": notes}
		).insert(ignore_permissions=True)

	def test_delete_leaves_a_permanent_record_of_the_row(self):
		reading = self._reading(exception_type="other", notes="تصحيح يدوي")
		docname = reading.name

		frappe.delete_doc("Meter Reading", docname, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("Meter Reading", docname))
		rows = frappe.get_all(
			"Reading Deletion Log",
			filters={"reading": docname},
			fields=["reading", "meter_code", "station_name", "shift_date", "start_reading",
				"end_reading", "liters_sold", "exception_type", "notes", "deleted_by", "deleted_at"],
		)
		self.assertEqual(len(rows), 1, "the deletion must leave exactly one log row")
		row = rows[0]
		self.assertEqual(row["meter_code"], self.meter.meter_code)
		self.assertEqual(row["station_name"], self.station.station_name)
		self.assertEqual(str(row["shift_date"]), "2026-10-01")
		self.assertEqual(row["start_reading"], 1000)
		self.assertEqual(row["end_reading"], 2000)
		self.assertEqual(row["liters_sold"], 1000)
		self.assertEqual(row["exception_type"], "other")
		self.assertEqual(row["notes"], "تصحيح يدوي")
		self.assertEqual(row["deleted_by"], frappe.session.user)
		self.assertTrue(row["deleted_at"])

	def test_one_log_row_per_deleted_reading(self):
		first = self._reading(start=1000, end=2000)
		second = self._reading(start=2000, end=2500)
		frappe.delete_doc("Meter Reading", first.name, ignore_permissions=True)
		frappe.delete_doc("Meter Reading", second.name, ignore_permissions=True)
		self.assertEqual(
			frappe.db.count("Reading Deletion Log", {"meter": self.meter.name}), 2
		)

	def test_the_log_is_readable_after_the_reading_is_gone(self):
		reading = self._reading()
		docname = reading.name
		frappe.delete_doc("Meter Reading", docname, ignore_permissions=True)
		found = frappe.db.exists("Reading Deletion Log", {"reading": docname})
		self.assertTrue(found)
		# and the docname is enough to look it up later — no Version rows needed
		self.assertFalse(
			frappe.db.exists("Version", {"ref_doctype": "Meter Reading", "docname": docname})
		)
