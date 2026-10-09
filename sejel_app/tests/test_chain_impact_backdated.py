import frappe
from frappe.tests.utils import FrappeTestCase
from sejel_app.api.dashboard import _single_station_payload


class TestChainImpactBackdatedEntry(FrappeTestCase):
	"""The impact lookup must work when several days were entered in ONE sitting.

	Every row then carries the same `recorded_at` (the typing clock), so a
	lookup ordered or filtered by `recorded_at` cannot find "the next day" —
	which is exactly how the customer enters yesterday and today.
	"""

	def setUp(self):
		suffix = frappe.utils.random_string(5)
		self.fuel = frappe.get_doc(
			{"doctype": "Fuel Type", "fuel_name": "بنزين QA " + suffix}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "Fuel Price", "fuel_type": self.fuel.name, "selling_price": 2.0,
			 "cost_per_liter": 1.5, "effective_date": "2026-01-01", "is_active": 1}
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
		doc.recorded_at = "2026-10-09 14:56:13"  # one sitting, one clock
		doc.insert(ignore_permissions=True)
		return doc

	def test_next_day_is_found_when_entry_timestamps_are_shared(self):
		self._reading("2026-10-01", 1000, 2000)
		self._reading("2026-10-02", 2000, 2600)
		self._reading("2026-10-03", 2600, 3000)

		payload = _single_station_payload(self.station.name, "2026-10-01", "manager")
		entry = next(m for m in payload["meters"] if m["id"] == self.meter.name)
		self.assertIsNotNone(entry["chain_impact"])
		self.assertEqual(str(entry["chain_impact"]["date"]), "2026-10-02")
		self.assertEqual(entry["chain_impact"]["start_reading"], 2000)

	def test_no_impact_when_the_shown_day_is_the_latest(self):
		self._reading("2026-10-01", 1000, 2000)
		self._reading("2026-10-02", 2000, 2600)
		payload = _single_station_payload(self.station.name, "2026-10-02", "manager")
		entry = next(m for m in payload["meters"] if m["id"] == self.meter.name)
		self.assertIsNone(entry["chain_impact"])
