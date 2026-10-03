import frappe
from frappe import _
from frappe.utils import now_datetime, getdate
from frappe.model.document import Document


class Shift(Document):
	@property
	def crosses_midnight(self):
		return self.end_time is not None and self.end_time <= self.start_time

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

	def _fuel_totals(self):
		"""Aggregate liters sold per fuel type for this shift."""
		fuel_summaries = {}
		readings = frappe.get_all(
			"Meter Reading",
			filters={"shift": self.name},
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

	def _calculate_expected_sales(self, total_liters):
		"""Calculate expected sales using frozen fuel prices."""
		if not total_liters:
			return 0

		fuel_summaries = self._fuel_totals()

		total = 0
		for fuel_type, liters in fuel_summaries.items():
			total += liters * self._frozen_price(fuel_type, self.date)

		return total

	def _create_fuel_summaries(self, reconciliation):
		"""Create per-fuel-type Shift Fuel Summary rows (frozen price at close)."""
		for fuel_type, liters in self._fuel_totals().items():
			price = self._frozen_price(fuel_type, self.date)
			summary = frappe.new_doc("Shift Fuel Summary")
			summary.reconciliation = reconciliation.name
			summary.fuel_type = fuel_type
			summary.liters_sold = liters
			summary.unit_price = price
			summary.expected_sales = liters * price
			summary.insert()
