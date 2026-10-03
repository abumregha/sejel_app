import frappe
from frappe import _
from frappe.model.document import Document


class TankTransfer(Document):
	def validate(self):
		self.check_same_tank()
		self.check_same_station()
		self.check_same_fuel()
		self.check_positive_quantity()

	def on_update(self):
		self.apply_level_changes()

	def check_same_tank(self):
		if self.from_tank == self.to_tank:
			frappe.throw(_("لا يمكن التحويل إلى نفس الخزان"))

	def check_same_station(self):
		from_station = frappe.db.get_value("Tank", self.from_tank, "station")
		to_station = frappe.db.get_value("Tank", self.to_tank, "station")
		if from_station != to_station:
			frappe.throw(_("الخزانات تجب إلى نفس المحطة"))

	def check_same_fuel(self):
		from_fuel = frappe.db.get_value("Tank", self.from_tank, "fuel_type")
		to_fuel = frappe.db.get_value("Tank", self.to_tank, "fuel_type")
		if from_fuel != to_fuel:
			frappe.throw(_("لا يمكن التحويل بين خزانين مختلفين في نوع الوقود"))
		if self.fuel_type and self.fuel_type != from_fuel:
			self.fuel_type = from_fuel

	def check_positive_quantity(self):
		if (self.quantity or 0) <= 0:
			frappe.throw(_("الكمية محددة اقل من صفر"))

	def apply_level_changes(self):
		"""Update tank levels: source -qty, destination +qty."""
		if self.status == "cancelled":
			return
		from_level = frappe.db.get_value("Tank", self.from_tank, "current_level") or 0
		to_level = frappe.db.get_value("Tank", self.to_tank, "current_level") or 0
		frappe.db.set_value("Tank", self.from_tank, "current_level", from_level - (self.quantity or 0))
		frappe.db.set_value("Tank", self.to_tank, "current_level", to_level + (self.quantity or 0))
