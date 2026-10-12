import frappe
from frappe import _
from frappe.utils import now_datetime, getdate
from frappe.model.document import Document


class Shift(Document):
	@property
	def crosses_midnight(self):
		return self.end_time is not None and self.end_time <= self.start_time

	def validate(self):
		LOCKED_FIELDS = {
			"submitted": ["date", "start_time", "end_time", "status"],
			"closed": ["shift_name", "station", "definition", "employee", "island",
					   "date", "start_time", "end_time", "status"],
		}
		locked = LOCKED_FIELDS.get(self.status, [])
		if not locked:
			return
		if self.get_db_value:
			db_status = self.get_db_value("status")
			if db_status and db_status != self.status:
				locked = [f for f in locked if f != "status"]
			for field in locked:
				db_val = self.get_db_value(field)
				cur_val = self.get(field)
				if str(db_val or "") != str(cur_val or ""):
					frappe.throw(
						_("لا يمكن تعديل حقل «{0}» في مناوبة بحالة «{1}»").format(
							_(self.meta.get_label(field)), _(self.status)
						),
						frappe.ValidationError,
					)

	def _log_correction(self, field_changed, old_value, new_value, reason=""):
		log = frappe.new_doc("Shift Correction Log")
		log.parent = self.name
		log.parenttype = "Shift"
		log.parentfield = "correction_log"
		log.corrected_by = frappe.session.user
		log.corrected_at = now_datetime()
		log.field_changed = field_changed
		log.old_value = str(old_value) if old_value else ""
		log.new_value = str(new_value) if new_value else ""
		log.reason = reason
		log.insert(ignore_permissions=True)

	def close_shift(self):
		"""Close shift and create reconciliation."""
		if self.status != "submitted":
			frappe.throw(_("المناوبة تحتاج إففالها قبل إغلاقها"))

		self.status = "closed"
		self.closed_by = frappe.session.user
		self.closed_at = now_datetime()
		self.save()

		self._validate_prices_configured()
		self.create_reconciliation()

	def create_reconciliation(self):
		"""Create financial reconciliation for this shift.

		Refuses to write a second reconciliation for the same shift: closing a
		day twice produced two identical financial records (2026-10-03).
		"""
		# Note: Shift / Meter Reading / Cash Collection / Voucher / POS Record are
		# not submittable DocTypes in this app, so records created via the API are
		# drafts (docstatus = 0). Filtering by docstatus = 1 would yield zero rows.
		if frappe.db.exists("Reconciliation", {"shift": self.name}):
			frappe.throw(_("يوجد تسوية مالية مسجلة لهذه المناوبة بالفعل"))

		readings = frappe.get_all(
			"Meter Reading",
			filters={"shift": self.name},
			fields=["meter", "liters_sold"],
		)

		total_liters = sum(r.liters_sold or 0 for r in readings)
		expected_sales = self._calculate_expected_sales(total_liters)

		total_cash = frappe.db.sql(
			"""SELECT COALESCE(SUM(amount), 0) FROM `tabCash Collection`
			WHERE shift = %s AND is_cancelled = 0""",
			self.name,
		)[0][0]

		total_vouchers = frappe.db.sql(
			"""SELECT COALESCE(SUM(total_value), 0) FROM `tabVoucher`
			WHERE shift = %s AND is_cancelled = 0""",
			self.name,
		)[0][0]

		total_pos = frappe.db.sql(
			"""SELECT COALESCE(SUM(total_amount), 0) FROM `tabPOS Record`
			WHERE shift = %s AND is_cancelled = 0""",
			self.name,
		)[0][0]

		# Cash expenses (invariant §1.6): only cash-method, pending/approved
		# expenses hit the cash position. Prefer expenses linked to this shift;
		# fall back to the station's unassigned cash expenses for the shift date
		# (the SPA's expense form records station+date, not always the shift).
		cash_expenses = self._cash_expenses()

		total_collection = total_cash + total_vouchers + total_pos
		difference = total_collection - expected_sales

		recon = frappe.new_doc("Reconciliation")
		recon.shift = self.name
		recon.station = self.station
		recon.total_liters = total_liters
		recon.expected_sales = expected_sales
		recon.total_cash = total_cash
		recon.total_vouchers = total_vouchers
		recon.total_pos = total_pos
		recon.total_collection = total_collection
		recon.total_expenses = cash_expenses
		recon.net_cash = total_cash - cash_expenses
		recon.difference = difference
		recon.difference_type = (
			"matched" if difference == 0
			else "surplus" if difference > 0
			else "shortage"
		)
		recon.status = "draft"
		recon.insert()
		self._create_fuel_summaries(recon)
		return recon

	def refresh_reconciliation(self, exclude=None):
		"""Recompute the reading-derived totals of an existing Reconciliation.

		Editing or deleting a reading of a CLOSED day changes litres and expected
		sales, but the Reconciliation was frozen at close time, so the day's
		financial record silently disagreed with the readings it came from. The
		cash side (collections, vouchers, POS, expenses) cannot change by
		editing a meter, so only the reading-derived fields move.

		`exclude` is the reading being deleted: Frappe runs on_trash BEFORE the
		row leaves the table, so without it a delete would recompute the same
		liters it is trying to remove.

		db.set_value / ignore_permissions on purpose: this runs inside the
		reading's own save, i.e. inside whatever session made the edit — a
		supervisor has no Reconciliation write permission and must still be able
		to correct their own reading.
		"""
		recon_name = frappe.db.exists("Reconciliation", {"shift": self.name})
		if not recon_name:
			return

		recon = frappe.get_doc("Reconciliation", recon_name)
		filters = {"shift": self.name}
		if exclude:
			filters["name"] = ["!=", exclude]
		total_liters = sum(
			(r.liters_sold or 0)
			for r in frappe.get_all("Meter Reading", filters=filters, fields=["liters_sold"])
		)
		expected_sales = self._calculate_expected_sales(total_liters, exclude=exclude)
		# Cash expenses are operational rows too: adding or editing one on a
		# closed day must move total_expenses / net_cash, not just the litres.
		cash_expenses = self._cash_expenses()
		difference = (recon.total_collection or 0) - expected_sales
		frappe.db.set_value(
			"Reconciliation",
			recon_name,
			{
				"total_liters": total_liters,
				"expected_sales": expected_sales,
				"total_expenses": cash_expenses,
				"net_cash": (recon.total_cash or 0) - cash_expenses,
				"difference": difference,
				"difference_type": (
					"matched" if difference == 0 else "surplus" if difference > 0 else "shortage"
				),
			},
		)

		# The set of fuels with litres can shrink to nothing when an edit zeroes
		# a fuel's only reading, so rebuild the rows rather than updating them.
		for row in frappe.get_all(
			"Shift Fuel Summary", filters={"reconciliation": recon_name}, fields=["name"]
		):
			frappe.delete_doc("Shift Fuel Summary", row.name, ignore_permissions=True)
		self._create_fuel_summaries(frappe.get_doc("Reconciliation", recon_name), exclude=exclude)

	def _fuel_totals(self, exclude=None):
		"""Aggregate liters sold per fuel type for this shift.

		`exclude` skips a reading that is being deleted: on_trash fires before
		the row leaves the table.
		"""
		fuel_summaries = {}
		filters = {"shift": self.name}
		if exclude:
			filters["name"] = ["!=", exclude]
		readings = frappe.get_all(
			"Meter Reading",
			filters=filters,
			fields=["meter", "liters_sold"],
		)

		for reading in readings:
			if not reading.liters_sold:
				continue
			meter = frappe.get_doc("Meter", reading.meter)
			fuel_type = meter.fuel_type
			if fuel_type not in fuel_summaries:
				fuel_summaries[fuel_type] = 0
			fuel_summaries[fuel_type] += reading.liters_sold
		return fuel_summaries

	def _cash_expenses(self):
		"""Cash-method expenses for this shift (fallback: station + shift date)."""
		linked = frappe.db.sql(
			"""SELECT COALESCE(SUM(amount), 0) FROM `tabExpense`
			WHERE shift = %s AND payment_method = 'cash'
			AND status IN ('pending', 'approved')""",
			self.name,
		)[0][0] or 0
		if linked:
			return linked
		return frappe.db.sql(
			"""SELECT COALESCE(SUM(amount), 0) FROM `tabExpense`
			WHERE station = %s AND (shift IS NULL OR shift = '')
			AND payment_method = 'cash' AND status IN ('pending', 'approved')
			AND DATE(creation) = %s""",
			(self.station, getdate(self.date)),
		)[0][0] or 0

	@staticmethod
	def _frozen_price(fuel_type, shift_date):
		"""Selling price effective on the shift date (invariant §1.2).

		Uses the latest Fuel Price whose effective_date <= shift.date; if none
		was published yet (backdated history), falls back to the earliest
		available price rather than zero, keeping historical closes meaningful.
		"""
		price = frappe.db.sql(
			"""SELECT selling_price FROM `tabFuel Price`
			WHERE fuel_type = %s AND is_active = 1 AND effective_date <= %s
			ORDER BY effective_date DESC LIMIT 1""",
			(fuel_type, getdate(shift_date)),
		)
		if price:
			return price[0][0] or 0
		price = frappe.db.sql(
			"""SELECT selling_price FROM `tabFuel Price`
			WHERE fuel_type = %s AND is_active = 1
			ORDER BY effective_date ASC LIMIT 1""",
			(fuel_type,),
		)
		return (price[0][0] if price else 0) or 0

	def _validate_prices_configured(self):
		"""Refuse to close a day whose fuel has no price.

		_frozen_price() returns 0 when no Fuel Price exists, so a station with no
		price configured closed its day reporting expected sales of 0.00 and a
		shortage equal to the whole day's fuel - silently, with no warning
		anywhere (QA-33). Better to stop, name the fuel, and say what to do.
		"""
		missing = []
		for fuel_type, liters in self._fuel_totals().items():
			if not liters:
				continue
			if not self._frozen_price(fuel_type, self.date):
				name = frappe.db.get_value("Fuel Type", fuel_type, "fuel_name") or fuel_type
				missing.append(name)
		if missing:
			frappe.throw(
				_(
					"لا يمكن إقفال اليوم: لم يتم ضبط سعر بيع لـ {0}. "
					"أضف سعر الوقود من صفحة «أسعار الوقود» ثم أعد المحاولة."
				).format("، ".join(missing)),
				frappe.ValidationError,
			)

	def _calculate_expected_sales(self, total_liters, exclude=None):
		"""Calculate expected sales using frozen fuel prices."""
		if not total_liters:
			return 0

		fuel_summaries = self._fuel_totals(exclude=exclude)

		total = 0
		for fuel_type, liters in fuel_summaries.items():
			total += liters * self._frozen_price(fuel_type, self.date)

		return total

	def _create_fuel_summaries(self, reconciliation, exclude=None):
		"""Create per-fuel-type Shift Fuel Summary rows (frozen price at close)."""
		for fuel_type, liters in self._fuel_totals(exclude=exclude).items():
			price = self._frozen_price(fuel_type, self.date)
			summary = frappe.new_doc("Shift Fuel Summary")
			summary.reconciliation = reconciliation.name
			summary.fuel_type = fuel_type
			summary.liters_sold = liters
			summary.unit_price = price
			summary.expected_sales = liters * price
			summary.insert()
