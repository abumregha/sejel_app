import frappe
from frappe import _
from frappe.model.document import Document


class TankTransfer(Document):
	def validate(self):
		self.check_same_tank()
		self.check_same_station()
		self.check_same_fuel()
		self.check_positive_quantity()
		# The stock movement is applied exactly once, on insert (see
		# after_insert), so the capacity rules only have meaning while that
		# movement is about to happen. Re-running them on a later save would
		# measure the tank AFTER it has already been debited.
		if self.is_new():
			self.check_source_has_the_quantity()
			self.check_destination_has_the_room()

	def after_insert(self):
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

	def check_source_has_the_quantity(self):
		"""The source may not be driven below zero (2026-10-03: a transfer of
		25,000 L from a 20,000 L tank was accepted and the inventory report then
		showed -5,000 L with no message anywhere)."""
		level = frappe.db.get_value("Tank", self.from_tank, "current_level") or 0
		if (self.quantity or 0) > level:
			frappe.throw(
				_("الكمية المطلوبة ({0} لتر) أكبر من المتاح في الخزان المصدر ({1} لتر)").format(
					self.quantity, level
				)
			)

	def check_destination_has_the_room(self):
		"""The destination may not be driven above its capacity."""
		level = frappe.db.get_value("Tank", self.to_tank, "current_level") or 0
		capacity = frappe.db.get_value("Tank", self.to_tank, "capacity") or 0
		if level + (self.quantity or 0) > capacity:
			frappe.throw(
				_("لا يتسع الخزان الوجهة: سعته {0} لتر وفيه {1} لتر — المتاح {2} لتر فقط").format(
					capacity, level, capacity - level
				)
			)

	def apply_level_changes(self):
		"""Update tank levels: source -qty, destination +qty.

		Called once, from after_insert. It used to run on every on_update, so
		any later save of the same transfer (a status change, a corrected
		quantity) moved the stock a SECOND time — silently.
		"""
		if self.status == "cancelled":
			return
		from_level = frappe.db.get_value("Tank", self.from_tank, "current_level") or 0
		to_level = frappe.db.get_value("Tank", self.to_tank, "current_level") or 0
		frappe.db.set_value("Tank", self.from_tank, "current_level", from_level - (self.quantity or 0))
		frappe.db.set_value("Tank", self.to_tank, "current_level", to_level + (self.quantity or 0))
