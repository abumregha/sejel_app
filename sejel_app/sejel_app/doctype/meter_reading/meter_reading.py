import frappe
from frappe import _
from frappe.model.document import Document


class MeterReading(Document):
	def validate(self):
		# Reading source (prompt §32): manual today; automatic/imported readings
		# from a future hardware layer feed the same canonical workflow.
		if not self.source:
			self.source = "manual"
		self.flag_opening_baseline()
		# Timestamp every reading — "latest reading per meter" and continuity
		# both order on recorded_at; API-created rows had it NULL, which made
		# latest-per-meter nondeterministic.
		if not self.recorded_at:
			self.recorded_at = frappe.utils.now_datetime()
		self.calculate_liters_sold()
		self.validate_continuity()

	def flag_opening_baseline(self):
		"""Mark the first reading of a meter that has no established counter.

		The readings screen sends the opening value from `Meter.current_reading`
		(`ReadingsView.prevOf`). A meter created by the setup wizard starts at
		0/None, so that fallback used to book the meter's **entire cumulative
		total** as one day's sale — QA-32 measured 8 guns entered at 1,000 L
		each being recorded as 807,849 L / 121,177 د.ل instead of 8,000 L /
		1,200 د.ل. The overflow then flows into the reconciliation, the daily
		report and the shortage verdict.

		So: the first reading of a meter that has neither a previous reading nor
		a counter is a **baseline**, not a sale. It is flagged (is_opening) and
		books 0 litres; the next day books normally against it. A meter that
		already has a counter, or any meter with earlier readings, is untouched.
		"""
		if not self.meter:
			return
		if not self.is_opening:
			earlier = frappe.get_all(
				"Meter Reading",
				filters={"meter": self.meter, "name": ["!=", self.name]},
				limit_page_length=1,
				fields=["name"],
			)
			counter = frappe.db.get_value("Meter", self.meter, "current_reading")
			if not earlier and not counter:
				self.is_opening = 1

	def calculate_liters_sold(self):
		# Use `is not None`, not truthiness: 0 is a legitimate previous reading
		# for a brand-new gun starting from zero, and end−0 must still compute.
		if self.is_opening:
			# A baseline establishes the counter — it is not fuel that was sold.
			self.liters_sold = 0
		elif self.start_reading is not None and self.end_reading is not None:
			self.liters_sold = self.end_reading - self.start_reading
		elif self.start_reading is not None and self.end_reading is None:
			self.liters_sold = 0

	def validate_continuity(self):
		"""Continuity requires a documented reason (Phase-2 decision Q-continuity).

		A gap (start != previous end) or a backwards counter (end < start) is
		only accepted with an exception_type (+ notes = the reason). Silent gaps
		are rejected in Arabic. Rows without readings yet pass — continuity is
		only checked when a start reading is provided.
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

		# A backwards counter is either a typo or a genuine reset/replacement.
		# Decide on the exception FIRST so a real meter reset is recoverable by
		# the operator. The previous order rejected every backwards counter
		# before the exception type was looked at, so the exception flow could
		# never take effect (QA-10). An unexplained backwards counter is still
		# refused outright.
		if (
			self.end_reading is not None
			and self.start_reading is not None
			and self.end_reading < self.start_reading
		):
			if not self.exception_type:
				frappe.throw(
					_(
						"القراءة الحالية ({0}) أقل من القراءة السابقة ({1}). إذا تم تصفير "
						"العداد أو استبداله، اختر نوع الاستثناء لتسجيل السبب"
					).format(self.end_reading, self.start_reading)
				)
			if not (self.notes or "").strip():
				frappe.throw(_("الرجاء كتابة سبب الاستثناء في حقل الملاحظات"))
			# A reset or a replacement zeroes the counter, so the reading itself
			# IS the measurable quantity dispensed since then. Litres sold before
			# the reset are unknowable and cannot be recovered - the exception is
			# the audit trail for them. An unexplained backwards move gets no
			# guess at all.
			if self.exception_type in ("reset", "replacement"):
				self.liters_sold = self.end_reading
			else:
				self.liters_sold = 0

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
		if not self.meter:
			return
		# An edit may target any date, so writing this row's end into the
		# counter blindly rewound the meter when an OLDER row was corrected
		# while newer rows exist. Recompute from the meter's latest CLOSED row
		# (the ordering the dashboard uses). A pending entry (no closing
		# reading yet) stores 0, and the counter has always ignored those —
		# they must not zero a counter an operator already established.
		# Plain SQL: the ["is", "set"] filter is rewritten to `<> ''`, which
		# Postgres rejects on a numeric column.
		rows = frappe.db.sql(
			"""
			select end_reading from `tabMeter Reading`
			where meter = %s and end_reading is not null and end_reading != 0
			order by recorded_at desc, name desc limit 1
			""",
			(self.meter,),
		)
		if rows:
			frappe.db.set_value("Meter", self.meter, "current_reading", rows[0][0])

	def on_trash(self):
		# Meter.current_reading is a denormalised copy of the LAST reading, so
		# deleting a reading without rolling it back leaves the next cycle's
		# "previous reading" pointing at a row that no longer exists — the
		# operator is shown a phantom previous value and the QA-32 opening
		# baseline is skipped. Recompute from whatever remains.
		if not self.meter:
			return
		# Plain SQL: the ["is", "set"] filter operator is rewritten to `<> ''`,
		# which Postgres rejects on a numeric column.
		rows = frappe.db.sql(
			"""
			select end_reading from `tabMeter Reading`
			where meter = %s and name != %s and end_reading is not null
			order by recorded_at desc, creation desc limit 1
			""",
			(self.meter, self.name),
		)
		# 0, not None: the column is NOT NULL, and 0 is exactly what
		# flag_opening_baseline() needs to see so the meter's next reading is
		# booked as a baseline again instead of a full-counter sale.
		frappe.db.set_value("Meter", self.meter, "current_reading", rows[0][0] if rows else 0)
