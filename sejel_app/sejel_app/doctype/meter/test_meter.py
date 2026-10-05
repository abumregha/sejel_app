import frappe
from frappe.tests.utils import FrappeTestCase


class TestMeterInitialValue(FrappeTestCase):
	def setUp(self):
		suffix = frappe.utils.random_string(5)
		self.fuel = frappe.get_doc(
			{"doctype": "Fuel Type", "fuel_name": "بنزين QA " + suffix}
		).insert(ignore_permissions=True)
		self.station = frappe.get_doc(
			{"doctype": "Station", "station_name": "محطة QA " + suffix}
		).insert(ignore_permissions=True)
		self.island = frappe.get_doc(
			{
				"doctype": "Island",
				"island_name": "جزيرة QA",
				"station": self.station.name,
				"number": 1,
			}
		).insert(ignore_permissions=True)
		self.machine = frappe.get_doc(
			{
				"doctype": "Machine",
				"machine_name": "مضخة QA",
				"island": self.island.name,
				"station": self.station.name,
				"number": 1,
			}
		).insert(ignore_permissions=True)
		self.tank = frappe.get_doc(
			{
				"doctype": "Tank",
				"tank_name": "خزان QA",
				"station": self.station.name,
				"fuel_type": self.fuel.name,
				"capacity": 10000,
			}
		).insert(ignore_permissions=True)
		self.meter = frappe.get_doc(
			{
				"doctype": "Meter",
				"meter_code": "QA" + suffix,
				"machine": self.machine.name,
				"fuel_type": self.fuel.name,
				"tank": self.tank.name,
				"current_reading": 5000,
			}
		).insert(ignore_permissions=True)
		self.shift = frappe.get_doc(
			{
				"doctype": "Shift",
				"shift_name": "مناوبة QA " + suffix,
				"station": self.station.name,
				"date": frappe.utils.today(),
				"start_time": "06:00",
				"end_time": "14:00",
			}
		).insert(ignore_permissions=True)

	def _add_reading(self, start, end):
		reading = frappe.get_doc(
			{
				"doctype": "Meter Reading",
				"shift": self.shift.name,
				"meter": self.meter.name,
				"start_reading": start,
				"end_reading": end,
			}
		)
		reading.insert(ignore_permissions=True)
		return reading

	def _db_counter(self):
		return frappe.db.get_value("Meter", self.meter.name, "current_reading")

	def test_counter_writable_before_first_reading(self):
		self.meter.current_reading = 9999.5
		self.meter.save()
		self.assertEqual(self._db_counter(), 9999.5)

	def test_insert_with_counter_allowed(self):
		doc = frappe.get_doc(
			{
				"doctype": "Meter",
				"meter_code": "QA" + frappe.utils.random_string(5),
				"machine": self.machine.name,
				"fuel_type": self.fuel.name,
				"tank": self.tank.name,
				"current_reading": 123,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.current_reading, 123)

	def test_counter_refused_after_first_reading(self):
		self._add_reading(5000, 7000)
		meter = frappe.get_doc("Meter", self.meter.name)
		meter.current_reading = 999999
		self.assertRaises(frappe.ValidationError, meter.save)
		# reading save re-derived the counter through set_value (bypasses validate)
		self.assertEqual(self._db_counter(), 7000)

	def test_resync_to_last_end_allowed(self):
		self._add_reading(5000, 7000)
		# simulate counter drift the way a bad cleanup would (direct SQL)
		frappe.db.set_value("Meter", self.meter.name, "current_reading", 1)
		meter = frappe.get_doc("Meter", self.meter.name)
		meter.current_reading = 7000
		meter.save()
		self.assertEqual(self._db_counter(), 7000)

	def test_negative_refused(self):
		meter = frappe.get_doc("Meter", self.meter.name)
		meter.current_reading = -1
		self.assertRaises(frappe.ValidationError, meter.save)
