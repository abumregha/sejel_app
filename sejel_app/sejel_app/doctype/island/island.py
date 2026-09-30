import frappe
from frappe.model.document import Document


class Island(Document):
	def validate(self):
		# Server-side numbering (Q48): the SPA no longer computes numbers from
		# (possibly truncated) lists. Continue after the highest existing number.
		if not self.number:
			self.number = (
				frappe.db.sql(
					"""SELECT COALESCE(MAX(number), 0) + 1
					   FROM `tabIsland` WHERE station = %s""",
					self.station,
				)[0][0]
				or 1
			)
		# Default name follows the seed convention جزيرة N
		if not self.island_name:
			self.island_name = "جزيرة {}".format(self.number)
