import frappe
from frappe.model.document import Document


class TankReading(Document):
	def validate(self):
		if not self.recorded_by:
			self.recorded_by = frappe.session.user

	def on_update(self):
		frappe.db.set_value("Tank", self.tank, {
			"current_level": self.reading_level,
			"last_reading_date": self.recorded_at,
		})
