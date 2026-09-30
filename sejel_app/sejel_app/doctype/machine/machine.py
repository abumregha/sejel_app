import frappe
from frappe.model.document import Document


class Machine(Document):
	def validate(self):
		if self.island:
			self.station = frappe.db.get_value("Island", self.island, "station")

		# Server-side numbering (Q48): unique number is per-island; the display
		# name follows the seed convention of station-wide counting (مضخة N).
		if not self.number and self.island:
			self.number = (
				frappe.db.sql(
					"""SELECT COALESCE(MAX(number), 0) + 1
					   FROM `tabMachine` WHERE island = %s""",
					self.island,
				)[0][0]
				or 1
			)
		if self.island and not self.machine_name:
			station_wide = frappe.db.sql(
				"""SELECT COUNT(*) FROM `tabMachine` m
				   JOIN `tabIsland` i ON i.name = m.island
				   WHERE i.station = %s""",
				self.station,
			)[0][0]
			self.machine_name = "مضخة {}".format(station_wide + 1)
