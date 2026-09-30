import frappe
from frappe import _
from frappe.model.document import Document


class MeterReading(Document):
	def validate(self):
		# Reading source (prompt §32): manual today; automatic/imported readings
		# from a future hardware layer feed the same canonical workflow.
		if not self.source:
			self.source = "manual"
		# Timestamp every reading — "latest reading per meter" and continuity
		# both order on recorded_at; API-created rows had it NULL, which made
		# latest-per-meter nondeterministic.
		if not self.recorded_at:
			self.recorded_at = frappe.utils.now_datetime()
		self.calculate_liters_sold()
		self.validate_continuity()

	def calculate_liters_sold(self):
		# Use `is not None`, not truthiness: 0 is a legitimate previous reading
		# for a brand-new gun starting from zero, and end−0 must still compute.
		if self.start_reading is not None and self.end_reading is not None:
			self.liters_sold = self.end_reading - self.start_reading
		elif self.start_reading is not None and self.end_reading is None:
			self.liters_sold = 0

	def validate_continuity(self):
		"""Continuity requires a documented reason (Phase-2 decision Q-continuity).

		A gap (start != previous end) or a negative span (end < start) is only
		accepted with an exception_type (+ notes = the reason). Silent gaps are
		rejected in Arabic. Rows without readings yet pass — continuity is only
		checked when a start reading is provided.
		"""
		if not self.meter or self.start_reading is None:
			return

		previous = frappe.get_all(
			"Meter Reading",
			filters={"meter": self.meter, "name": ["!=", self.name]},
			order_by="recorded_at desc, name desc",
			limit_page_length=1,
			fields=["end_reading", "exception_type"],
		)

		# Negative span is never acceptable, reason or not
		if self.end_reading is not None and self.end_reading < self.start_reading:
			frappe.throw(_("قراءة الاختتام أقل من قراءة الافتتاح — راجع القراءة"))

		if previous and previous[0].end_reading is not None:
			last_end = previous[0].end_reading
			if self.start_reading != last_end:
				if not self.exception_type:
					frappe.throw(
						_("قراءة الافتتاح ({0}) لا تطابق آخر قراءة اختتام ({1}) — أدخل سبب الاستثناء للمتابعة").format(
							self.start_reading, last_end
						)
					)
				if not (self.notes or "").strip():
					frappe.throw(_("الرجاء كتابة سبب فجوة القراءة في حقل الملاحظات"))

	def on_update(self):
		if self.end_reading:
			frappe.db.set_value("Meter", self.meter, "current_reading", self.end_reading)
