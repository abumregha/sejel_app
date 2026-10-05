import frappe
from frappe import _
from frappe.model.document import Document

MAX_INITIAL_READING = 1e9
RESYNC_TOLERANCE = 0.001


class Meter(Document):
	def validate(self):
		if not self.has_value_changed("current_reading"):
			return
		if self.current_reading is None:
			return
		try:
			value = float(self.current_reading)
		except (TypeError, ValueError):
			frappe.throw(_("قيمة غير صالحة للقراءة الافتتاحية"))
		if value != value or value < 0 or value > MAX_INITIAL_READING:
			frappe.throw(_("قيمة غير صالحة للقراءة الافتتاحية: {0}").format(self.current_reading))
		self.current_reading = value
		rows = frappe.db.count("Meter Reading", filters={"meter": self.name})
		if not rows:
			return
		last_end = frappe.db.get_value(
			"Meter Reading", {"meter": self.name}, "end_reading", order_by="creation desc"
		)
		if last_end is not None and abs(value - float(last_end)) <= RESYNC_TOLERANCE:
			return
		frappe.throw(
			_("لا يمكن تعديل القراءة الافتتاحية للعداد {0} — عليها {1} قراءة محفوظة").format(
				self.meter_code, rows
			)
		)
