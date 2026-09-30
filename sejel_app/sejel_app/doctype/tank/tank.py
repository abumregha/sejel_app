import frappe
from frappe.model.document import Document


class Tank(Document):
	def validate(self):
		if self.dedicated_to_machine:
			machine_station = frappe.db.get_value("Machine", self.dedicated_to_machine, "station")
			if machine_station and machine_station != self.station:
				frappe.throw(f"Machine {self.dedicated_to_machine} belongs to station {machine_station}, not {self.station}")

	@property
	def level_percent(self):
		return (self.current_level / self.capacity * 100) if self.capacity > 0 else 0

	def latest_reading(self):
		return frappe.get_all(
			"Tank Reading",
			filters={"tank": self.name},
			order_by="recorded_at desc, name desc",
			limit_page_length=1,
		)

	def total_sales_liters(self, since=None):
		filters = {"meter_fuel_type": self.fuel_type, "liters_sold": [">", 0]}
		if since:
			filters["recorded_at"] = [">=", since]
		result = frappe.db.sql(
			"""SELECT COALESCE(SUM(liters_sold), 0) FROM `tabMeter Reading`
			WHERE meter_fuel_type = %s AND liters_sold > 0 AND docstatus = 1
			AND (%s IS NULL OR recorded_at >= %s)""",
			(self.fuel_type, since, since),
		)
		return result[0][0] if result else 0

	def total_received(self, since=None):
		filters = {"tank": self.name, "received_quantity": ["is", "set"]}
		if since:
			filters["arrival_date"] = [">=", since]
		result = frappe.db.sql(
			"""SELECT COALESCE(SUM(received_quantity), 0) FROM `tabDelivery`
			WHERE tank = %s AND received_quantity IS NOT NULL AND docstatus = 1
			AND (%s IS NULL OR arrival_date >= %s)""",
			(self.name, since, since),
		)
		return result[0][0] if result else 0
