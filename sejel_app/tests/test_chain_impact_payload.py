import frappe
from frappe.tests.utils import FrappeTestCase
from sejel_app.api.dashboard import _single_station_payload


class TestChainImpactPayload(FrappeTestCase):
	"""The readings screen must be able to tell the operator WHICH later day and
	reconciliation a correction of this reading would affect — before they save,
	not after."""

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
		self.day1 = self._shift("2026-10-01")
		self.day2 = self._shift("2026-10-02")

	def _shift(self, day):
		return frappe.get_doc(
			{"doctype": "Shift", "shift_name": f"مناوبة QA {day}", "station": self.station.name,
			 "date": day, "is_day_close": 1, "start_time": "06:00", "end_time": "14:00"}
		).insert(ignore_permissions=True)

	def _reading(self, shift, start, end):
		doc = frappe.get_doc(
			{"doctype": "Meter Reading", "shift": shift.name, "meter": self.meter.name,
			 "start_reading": start, "end_reading": end}
		)
		doc.recorded_at = f"{shift.date} 23:00:00"
		doc.insert(ignore_permissions=True)
		return doc

	def _meter_entry(self, payload):
		return next(m for m in payload["meters"] if m["id"] == self.meter.name)

	def test_payload_exposes_the_next_day_and_its_reconciliation(self):
		self._reading(self.day1, 1000, 2000)
		self._reading(self.day2, 2000, 2600)

		# close day 2 so a Reconciliation exists for it
		shift = frappe.get_doc("Shift", self.day2.name)
		shift.status = "submitted"
		shift.save()
		shift.close_shift()

		payload = _single_station_payload(self.station.name, "2026-10-01", "manager")
		entry = self._meter_entry(payload)

		self.assertTrue(entry["chain_impact"])
		self.assertEqual(str(entry["chain_impact"]["date"]), "2026-10-02")
		self.assertEqual(entry["chain_impact"]["start_reading"], 2000)
		self.assertEqual(entry["chain_impact"]["recon"]["total_liters"], 600)
		self.assertEqual(entry["chain_impact"]["recon"]["expected_sales"], 1200.0)

	def test_no_chain_impact_on_the_latest_day(self):
		self._reading(self.day1, 1000, 2000)
		payload = _single_station_payload(self.station.name, "2026-10-01", "manager")
		self.assertIsNone(self._meter_entry(payload)["chain_impact"])
