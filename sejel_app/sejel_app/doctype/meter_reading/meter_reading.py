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

	def _chain_neighbours(self):
		"""The readings immediately before and after this one, in time.

		Continuity used to compare against the NEWEST other reading, which made
		every correction of an older day look like a gap, and it never checked
		the other direction — so a corrected end silently left the next day's
		start mismatched. Ordering by (recorded_at, name) is the order the
		dashboard's "latest reading per meter" and the counter recompute use, so
		all three agree on what "previous" means.
		"""
		rows = frappe.get_all(
			"Meter Reading",
			filters={"meter": self.meter, "name": ["!=", self.name]},
			fields=["name", "start_reading", "end_reading", "recorded_at"],
			order_by="recorded_at asc, name asc",
		)
		key = (str(self.recorded_at or ""), self.name)
		before = None
		after = None
		for row in rows:
			if (str(row.recorded_at or ""), row.name) < key:
				before = row  # ascending order: the last one below us wins
			elif after is None:
				after = row  # …and the first one above us
		return before, after

	def _require_reason(self, message):
		if not self.exception_type:
			frappe.throw(message)
		if not (self.notes or "").strip():
			frappe.throw(_("الرجاء كتابة سبب الاستثناء في حقل الملاحظات"))

	def validate_continuity(self):
		"""Continuity in BOTH directions requires a documented reason.

		A reading continues its own predecessor, and it must not silently break
		the day that follows it. Either mismatch is accepted with an
		exception_type + notes (the operator's own correction, or a genuine
		meter reset/replacement); a silent gap is refused in Arabic.
		"""
		if not self.meter or self.start_reading is None:
			return

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

		before, after = self._chain_neighbours()

		if before and before.end_reading is not None and self.start_reading != before.end_reading:
			self._require_reason(
				_(
					"القراءة السابقة ({0}) لا تطابق نهاية قراءة اليوم الذي قبلها ({1}) — "
					"أدخل سبب الاستثناء للمتابعة"
				).format(self.start_reading, before.end_reading)
			)

		if (
			after
			and after.start_reading is not None
			and self.end_reading is not None
			and self.end_reading != after.start_reading
		):
			self._require_reason(
				_(
					"نهاية هذه القراءة ({0}) لا تطابق بداية القراءة التالية ({1}) — "
					"أدخل سبب الاستثناء للمتابعة"
				).format(self.end_reading, after.start_reading)
			)

	def _refresh_reconciliation(self, exclude=None):
		# A reading of a CLOSED day has a Reconciliation built from it. Editing
		# or deleting it changes that day's litres, so the financial record has
		# to follow. Cheap no-op while the day is still open (no Reconciliation).
		if not self.shift:
			return
		if not frappe.db.exists("Reconciliation", {"shift": self.shift}):
			return
		frappe.get_doc("Shift", self.shift).refresh_reconciliation(exclude=exclude)

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
		self._refresh_reconciliation()

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
		self._refresh_reconciliation(exclude=self.name)
