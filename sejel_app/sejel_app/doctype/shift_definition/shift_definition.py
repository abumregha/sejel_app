import frappe
from frappe.model.document import Document


class ShiftDefinition(Document):
	def day_list(self):
		return [int(d) for d in self.days.split(",") if d.strip().isdigit()]

	def days_display(self):
		names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
		return ", ".join(names[d] for d in self.day_list() if d in names)
