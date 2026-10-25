import frappe
from frappe.utils import getdate, cint

from .scoping import scoped_station


def _station_name(station):
	return frappe.db.get_value("Station", station, "station_name") or station


def _resolve_station(doctype, name):
	if doctype == "Station":
		return name
	return frappe.db.get_value(doctype, name, "station")


def _scoped_station_list():
	"""Stations the current user may see (scoped users: just their own)."""
	station = scoped_station()
	if station:
		return [station]
	return frappe.get_all("Station", filters={"status": "active"}, pluck="name")


def monthly_report(year, month):
	"""Monthly financial report from Reconciliation (the money source of truth).

	Replaces the previous placeholder version that returned hardcoded zeros —
	the printed report was blank (client: "double check the printable monthly
	reports").
	"""
	year, month = cint(year), cint(month)
	if not year or not month or month < 1 or month > 12:
		frappe.throw("Year and month required")

	start = getdate("{}-{:02d}-01".format(year, month))
	if month == 12:
		end = getdate("{}-12-31".format(year))
	else:
		end = getdate("{}-{:02d}-01".format(year, month + 1))

	stations = _scoped_station_list()
	if not stations:
		return {
			"year": year, "month": month, "total_liters": 0,
			"total_expected_sales": 0, "total_collected": 0,
			"total_expenses": 0, "net_cash": 0, "total_shifts": 0,
			"difference": 0, "stations": [],
		}

	rows = frappe.db.sql(
		"""SELECT r.station,
			COUNT(*) AS shifts,
			SUM(r.total_liters) AS liters,
			SUM(r.expected_sales) AS expected_sales,
			SUM(r.total_cash) AS cash,
			SUM(r.total_vouchers) AS vouchers,
			SUM(r.total_pos) AS pos,
			SUM(r.total_collection) AS collected,
			SUM(r.total_expenses) AS expenses,
			SUM(r.net_cash) AS net_cash,
			SUM(r.difference) AS difference
		FROM `tabReconciliation` r
		JOIN `tabShift` s ON s.name = r.shift
		WHERE r.station IN %s AND s.date >= %s AND s.date < %s
		GROUP BY r.station""",
		(tuple(stations), start, end),
		as_dict=True,
	)

	# Per-fuel-type breakdown (mirrors Shift Fuel Summary rows) for the
	# printable monthly report's second table.
	fuel_rows = frappe.db.sql(
		"""SELECT fs.fuel_type,
			SUM(fs.liters_sold) AS liters,
			SUM(fs.expected_sales) AS expected_sales
		FROM `tabShift Fuel Summary` fs
		JOIN `tabReconciliation` r ON r.name = fs.reconciliation
		JOIN `tabShift` s ON s.name = r.shift
		WHERE r.station IN %s AND s.date >= %s AND s.date < %s
		GROUP BY fs.fuel_type""",
		(tuple(stations), start, end),
		as_dict=True,
	)
	fuel_breakdown = [
		{
			"fuel_type": f.fuel_type,
			"liters": float(f.liters or 0),
			"expected_sales": float(f.expected_sales or 0),
		}
		for f in fuel_rows
	]

	by_station = {r.station: r for r in rows}
	stations_data = []
	totals = dict(liters=0, expected_sales=0, collected=0, expenses=0, net_cash=0, difference=0, shifts=0)
	for s in stations:
		r = by_station.get(s)
		stations_data.append({
			"id": s,
			"name": _station_name(s),
			"shifts": r.shifts if r else 0,
			"liters": float(r.liters or 0) if r else 0,
			"expected_sales": float(r.expected_sales or 0) if r else 0,
			"cash": float(r.cash or 0) if r else 0,
			"vouchers": float(r.vouchers or 0) if r else 0,
			"pos": float(r.pos or 0) if r else 0,
			"collected": float(r.collected or 0) if r else 0,
			"expenses": float(r.expenses or 0) if r else 0,
			"net_cash": float(r.net_cash or 0) if r else 0,
			"difference": float(r.difference or 0) if r else 0,
		})
		for k in totals:
			if k == "shifts":
				totals[k] += (r.shifts if r else 0)
			else:
				totals[k] += float(getattr(r, k, 0) or 0) if r else 0

	return {
		"year": year, "month": month,
		"total_liters": totals["liters"],
		"total_expected_sales": totals["expected_sales"],
		"total_collected": totals["collected"],
		"total_expenses": totals["expenses"],
		"net_cash": totals["net_cash"],
		"difference": totals["difference"],
		"total_shifts": totals["shifts"],
		"fuel_breakdown": fuel_breakdown,
		"stations": stations_data,
	}


def daily_report(date):
	"""Daily report with REAL money numbers from Reconciliation.

	The old version returned placeholder zeros for per-station sales while
	showing real liters — banned by the dashboard acceptance criteria (§27:
	"no fake/mock values").
	"""
	if not date:
		frappe.throw("Date required")
	d = getdate(date)

	stations = _scoped_station_list()
	rows = frappe.db.sql(
		"""SELECT r.station,
			COUNT(*) AS shifts,
			SUM(r.total_liters) AS liters,
			SUM(r.expected_sales) AS expected_sales,
			SUM(r.total_collection) AS collected,
			SUM(r.difference) AS difference
		FROM `tabReconciliation` r
		JOIN `tabShift` s ON s.name = r.shift
		WHERE r.station IN %s AND s.date = %s
		GROUP BY r.station""",
		(tuple(stations), d),
		as_dict=True,
	) if stations else []

	by_station = {r.station: r for r in rows}
	stations_data = []
	tot = dict(liters=0.0, expected=0.0, collected=0.0, difference=0.0, shifts=0)
	for s in stations:
		r = by_station.get(s)
		stations_data.append({
			"id": s,
			"name": _station_name(s),
			"shifts": r.shifts if r else 0,
			"liters": float(r.liters or 0) if r else 0,
			"expected_sales": float(r.expected_sales or 0) if r else 0,
			"collected": float(r.collected or 0) if r else 0,
			"difference": float(r.difference or 0) if r else 0,
		})
		if r:
			tot["liters"] += float(r.liters or 0)
			tot["expected"] += float(r.expected_sales or 0)
			tot["collected"] += float(r.collected or 0)
			tot["difference"] += float(r.difference or 0)
			tot["shifts"] += r.shifts

	return {
		"date": str(d),
		"total_liters": tot["liters"],
		"total_expected_sales": tot["expected"],
		"total_collected": tot["collected"],
		"difference": tot["difference"],
		"total_shifts": tot["shifts"],
		"stations": stations_data,
	}


def export_station_excel(view="station", name=""):
	"""Excel export of station data (client request): a full Station workbook
	(overview, shifts, reconciliations, tanks, deliveries), a Reconciliation
	detail, or a Shift detail — RTL sheets with Arabic headers.

	GET /api/export/?view=station|reconciliation|shift&name=<docname>
	Returns an .xlsx attachment.
	"""
	import io
	from openpyxl import Workbook
	from openpyxl.styles import Font, PatternFill, Alignment
	from openpyxl.utils import get_column_letter
	from werkzeug.wrappers import Response

	view = (view or "station").strip()
	if view not in ("station", "reconciliation", "shift"):
		frappe.throw("Unknown export view: {}".format(view))
	if not name:
		frappe.throw("Missing record name")

	# Map view → doctype and enforce station scoping before touching data.
	doctype = {"station": "Station", "reconciliation": "Reconciliation", "shift": "Shift"}[view]
	if not frappe.db.exists(doctype, name):
		frappe.throw("غير موجود: {}".format(name), frappe.DoesNotExistError)
	resolved = _resolve_station(doctype, name)
	if resolved is None:
		# Reconciliation/Shift always carry station; guard anyway
		frappe.throw("Cannot resolve station for export")
	scoped = scoped_station()
	if scoped and resolved != scoped:
		frappe.throw("غير مصرح لك بتصدير بيانات محطة أخرى", frappe.PermissionError)

	wb = Workbook()
	hdr_font = Font(bold=True, color="FFFFFF")
	hdr_fill = PatternFill("solid", fgColor="1F2937")

	def sheet(title, headers, rows):
		ws = wb.create_sheet(title)
		ws.sheet_view.rightToLeft = True
		ws.append(headers)
		for c in ws[1]:
			c.font = hdr_font
			c.fill = hdr_fill
			c.alignment = Alignment(horizontal="center")
		for row in rows:
			ws.append(row)
		for idx, h in enumerate(headers, start=1):
			width = max(
				[len(str(h)) * 1.6]
				+ [len(str(r[idx - 1])) + 4 for r in rows[:40] if idx - 1 < len(r)]
			)
			ws.column_dimensions[get_column_letter(idx)].width = min(max(width, 10), 45)
		if rows:
			ws.freeze_panes = "A2"
		return ws

	def kv_sheet(title, pairs):
		ws = wb.create_sheet(title)
		ws.sheet_view.rightToLeft = True
		ws.append(["البند", "القيمة"])
		for c in ws[1]:
			c.font = hdr_font
			c.fill = hdr_fill
		for row in pairs:
			ws.append(row)
		ws.column_dimensions["A"].width = 28
		ws.column_dimensions["B"].width = 40
		return ws

	if view == "reconciliation":
		recon = frappe.get_doc("Reconciliation", name)
		kv_sheet("التسوية", [
			("المحطة", _station_name(recon.station)),
			("المناوبة", recon.shift),
			("إجمالي اللترات", float(recon.total_liters or 0)),
			("المبيعات المتوقعة", float(recon.expected_sales or 0)),
			("النقدية", float(recon.total_cash or 0)),
			("الكوبونات", float(recon.total_vouchers or 0)),
			("POS", float(recon.total_pos or 0)),
			("إجمالي التحصيل", float(recon.total_collection or 0)),
			("المصروفات النقدية", float(recon.total_expenses or 0)),
			("صافي النقدية", float(recon.net_cash or 0)),
			("الفرق", float(recon.difference or 0)),
			("نوع الفرق", recon.difference_type),
			("الحالة", recon.status),
		])
		sheet("حسب نوع الوقود",
			["نوع الوقود", "اللترات", "سعر اللتر", "المبيعات المتوقعة"],
			[[s.fuel_type, float(s.liters_sold or 0), float(s.unit_price or 0), float(s.expected_sales or 0)]
			 for s in recon.get("fuel_summaries", [])])
	elif view == "shift":
		sh = frappe.get_doc("Shift", name)
		kv_sheet("المناوبة", [
			("المحطة", _station_name(sh.station)),
			("التاريخ", str(sh.date or "")),
			("الحالة", sh.status),
			("من", str(sh.start_time or "")),
			("إلى", str(sh.end_time or "")),
		])
		readings = frappe.get_all("Meter Reading", filters={"shift": name},
			fields=["meter", "attendant", "start_reading", "end_reading", "liters_sold", "recorded_at"])
		meter_codes = dict(frappe.get_all("Meter", pluck=["name", "meter_code"]))
		sheet("قراءات العدادات",
			["العداد", "المناوب", "الافتتاحية", "الختامية", "اللترات", "الوقت"],
			[[meter_codes.get(r.meter, r.meter), r.attendant or "",
			  float(r.start_reading or 0), float(r.end_reading or 0) if r.end_reading else "",
			  float(r.liters_sold or 0), str(r.recorded_at or "")] for r in readings])
		for title, dt, amt in (("التحصيل النقدي", "Cash Collection", "amount"),
							   ("الكوبونات", "Voucher", "total_value"),
							   ("الدفع الإلكتروني", "POS Record", "total_amount")):
			rows = frappe.get_all(dt, filters={"shift": name, "is_cancelled": 0},
				fields=[amt, "creation"])
			sheet(title, ["المبلغ", "الوقت"],
				[[float(r[amt] or 0), str(r.creation or "")] for r in rows])
	else:
		station = frappe.get_doc("Station", name)
		kv_sheet("نظرة عامة", [
			("اسم المحطة", station.station_name),
			("العنوان", station.address or ""),
			("الحالة", station.status),
			("نوع العلاقة", station.relationship_type or ""),
			("وقت إقفال اليوم", str(station.day_close_time or "")),
			("تاريخ التصدير", frappe.utils.now()),
		])
		shifts = frappe.get_all("Shift", filters={"station": name},
			fields=["date", "shift_name", "status", "is_day_close", "start_time", "end_time"], order_by="date desc")
		sheet("المناوبات", ["التاريخ", "الاسم", "النوع", "الحالة", "من", "إلى"],
			[[str(s.date or ""), s.shift_name or "",
			  ("إقفال اليوم" if s.is_day_close else "مناوبة موظف"),
			  s.status, str(s.start_time or ""), str(s.end_time or "")] for s in shifts])
		recons = frappe.get_all("Reconciliation", filters={"station": name},
			fields=["name", "modified", "total_liters", "expected_sales", "total_cash", "total_vouchers",
				"total_pos", "total_collection", "total_expenses", "net_cash", "difference", "difference_type", "status"],
			order_by="modified desc")
		sheet("التسويات المالية",
			["التاريخ (آخر تحديث)", "اللترات", "المبيعات المتوقعة", "النقدية", "الكوبونات", "POS",
			 "التحصيل", "المصروفات", "صافي النقدية", "الفرق", "نوع الفرق", "الحالة"],
			[[str(r.modified or ""), float(r.total_liters or 0), float(r.expected_sales or 0),
			  float(r.total_cash or 0), float(r.total_vouchers or 0), float(r.total_pos or 0),
			  float(r.total_collection or 0), float(r.total_expenses or 0), float(r.net_cash or 0),
			  float(r.difference or 0), r.difference_type, r.status] for r in recons])
		tanks = frappe.get_all("Tank", filters={"station": name},
			fields=["tank_name", "fuel_type", "capacity", "current_level"])
		sheet("الخزانات", ["الخزان", "نوع الوقود", "السعة", "الحالي", "النسبة %"],
			[[t.tank_name or t.name, t.fuel_type, float(t.capacity or 0), float(t.current_level or 0),
			  round((t.current_level or 0) / t.capacity * 100, 1) if t.capacity else 0] for t in tanks])
		deliveries = frappe.get_all("Delivery", filters={"station": name},
			fields=["order_date", "supplier", "fuel_type", "expected_quantity", "received_quantity", "shortage", "status"],
			order_by="order_date desc")
		sheet("الشحنات", ["التاريخ", "المورد", "النوع", "المتوقع", "المستلم", "النقص", "الحالة"],
			[[str(d.order_date or ""), d.supplier or "", d.fuel_type, float(d.expected_quantity or 0),
			  float(d.received_quantity or 0), float(d.shortage or 0), d.status] for d in deliveries])

	buf = io.BytesIO()
	wb.remove(wb.active)  # drop the default sheet
	wb.save(buf)

	resp = Response(buf.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
	resp.headers["Content-Disposition"] = "attachment; filename=sejel-{}-{}.xlsx".format(view, name.replace("/", "-"))
	return resp


def monthly_balance_report(year, month):
	"""Monthly balance report: deposits, shipment costs, rent, and running balance.

	Combines Station Deposit records with Stock Entry deductions (delivery + rent)
	to show the prepaid balance position for each station at month end.
	"""
	year, month = cint(year), cint(month)
	if not year or not month or month < 1 or month > 12:
		frappe.throw("Year and month required")

	import calendar
	last_day = calendar.monthrange(year, month)[1]
	start = getdate("{}-{:02d}-01".format(year, month))
	end = getdate("{}-{:02d}-{:02d}".format(year, month, last_day))

	stations = _scoped_station_list()
	if not stations:
		return {"year": year, "month": month, "stations": [], "totals": {}}

	station_rows = []
	totals = {"deposits": 0, "shipment_costs": 0, "rent": 0, "adjustments": 0, "balance": 0}

	for station in stations:
		deposits = frappe.get_all(
			"Station Deposit",
			filters=[
				["station", "=", station],
				["invoice_date", ">=", str(start)],
				["invoice_date", "<=", str(end)],
			],
			fields=["deposit_amount", "invoice_date", "invoice_number", "reference"],
		)
		total_deposits = sum(float(d.deposit_amount or 0) for d in deposits)

		stock_entries = frappe.get_all(
			"Stock Entry",
			filters=[
				["station", "=", station],
				["date", ">=", str(start)],
				["date", "<=", str(end)],
				["status", "=", "submitted"],
			],
			fields=["entry_type", "total_amount"],
		)
		shipment_costs = sum(float(e.total_amount or 0) for e in stock_entries if e.entry_type == "delivery")
		rent = sum(float(e.total_amount or 0) for e in stock_entries if e.entry_type == "rent")
		adjustments = sum(float(e.total_amount or 0) for e in stock_entries if e.entry_type == "adjustment")

		total_deductions = shipment_costs + rent + adjustments
		running_balance = total_deposits - total_deductions

		station_meta = frappe.db.get_value("Station", station, ["station_name", "show_rent"], as_dict=True)
		show_rent = station_meta.get("show_rent", 1) if station_meta else 1

		station_rows.append({
			"station": station,
			"station_name": _station_name(station),
			"deposits": total_deposits,
			"shipment_costs": shipment_costs,
			"rent": rent if show_rent else 0,
			"rent_hidden": not show_rent,
			"adjustments": adjustments,
			"total_deductions": total_deductions,
			"running_balance": running_balance,
		})
		totals["deposits"] += total_deposits
		totals["shipment_costs"] += shipment_costs
		totals["rent"] += rent if show_rent else 0
		totals["adjustments"] += adjustments
		totals["balance"] += running_balance

	return {
		"year": year,
		"month": month,
		"stations": station_rows,
		"totals": totals,
	}


def station_tank_summary(station=None):
	"""Total available fuel volume across all tanks for a station.

	Returns per-tank breakdown plus station-level totals per fuel type.
	"""
	if not station:
		station = scoped_station()
	if not station:
		st = frappe.get_all("Station", filters={"status": "active"}, limit=1, pluck="name")
		if st:
			station = st[0]
	if not station:
		frappe.throw("Station required")

	tanks = frappe.get_all(
		"Tank",
		filters={"station": station},
		fields=["name", "tank_name", "fuel_type", "capacity", "current_level"],
		order_by="fuel_type, tank_name",
	)

	fuel_type_totals = {}
	for t in tanks:
		ft = t.fuel_type or "unknown"
		if ft not in fuel_type_totals:
			fuel_type_totals[ft] = {"fuel_type": ft, "total_capacity": 0, "total_current": 0, "tank_count": 0}
		fuel_type_totals[ft]["total_capacity"] += float(t.capacity or 0)
		fuel_type_totals[ft]["total_current"] += float(t.current_level or 0)
		fuel_type_totals[ft]["tank_count"] += 1

	return {
		"station": station,
		"station_name": _station_name(station),
		"tanks": tanks,
		"fuel_type_totals": list(fuel_type_totals.values()),
		"grand_total_current": sum(float(t.current_level or 0) for t in tanks),
		"grand_total_capacity": sum(float(t.capacity or 0) for t in tanks),
	}


def delivery_print_report(station=None, start_date=None, end_date=None):
	"""Printable report of all delivered shipments for the marketing company.

	Shows: invoice number, actual delivery date, quantity received, tank.
	Flags extra shipments as "مرحلة" (transit) and undelivered as "undelivered".
	"""
	if not station:
		station = scoped_station()
	if not station:
		st = frappe.get_all("Station", filters={"status": "active"}, limit=1, pluck="name")
		if st:
			station = st[0]
	if not station:
		frappe.throw("Station required")

	filters = {"station": station, "status": ["in", ["received", "undelivered", "transit"]]}
	if start_date:
		filters["arrival_date"] = [">=", start_date]
	if end_date:
		filters["arrival_date"] = ["<=", end_date]

	deliveries = frappe.get_all(
		"Delivery",
		filters=filters,
		fields=["name", "invoice_number", "arrival_date", "received_quantity",
			"expected_quantity", "fuel_type", "tank", "is_unscheduled",
			"status", "order_date", "scheduled_date"],
		order_by="arrival_date desc",
	)

	tank_names = {}
	for d in deliveries:
		if d.tank and d.tank not in tank_names:
			tank_names[d.tank] = frappe.db.get_value("Tank", d.tank, "tank_name") or d.tank

	rows = []
	for d in deliveries:
		flag = ""
		if d.is_unscheduled:
			flag = "مرحلة"
		elif d.status == "undelivered":
			flag = "undelivered"
		elif d.status == "transit":
			flag = "transit"

		rows.append({
			"invoice_number": d.invoice_number or "—",
			"delivery_date": str(d.arrival_date or "—"),
			"order_date": str(d.order_date or "—"),
			"scheduled_date": str(d.scheduled_date or "—"),
			"fuel_type": d.fuel_type or "—",
			"tank": tank_names.get(d.tank, d.tank or "—"),
			"expected_quantity": float(d.expected_quantity or 0),
			"received_quantity": float(d.received_quantity or 0),
			"flag": flag,
			"status": d.status,
		})

	return {
		"station": station,
		"station_name": _station_name(station),
		"start_date": start_date,
		"end_date": end_date,
		"total_delivered": sum(1 for d in deliveries if d.status == "received"),
		"total_undelivered": sum(1 for d in deliveries if d.status == "undelivered"),
		"total_transit": sum(1 for d in deliveries if d.status == "transit"),
		"total_quantity_received": sum(float(d.received_quantity or 0) for d in deliveries),
		"deliveries": rows,
	}


def station_total_received(station=None):
	"""Total received fuel quantity tracked separately from tank-level readings.

	For late deliveries where workers can't measure accurately, this tracks
	the total received quantity without requiring pre/post tank readings.
	"""
	if not station:
		station = scoped_station()
	if not station:
		st = frappe.get_all("Station", filters={"status": "active"}, limit=1, pluck="name")
		if st:
			station = st[0]
	if not station:
		frappe.throw("Station required")

	received = frappe.db.sql(
		"""SELECT COALESCE(SUM(received_quantity), 0) FROM `tabDelivery`
		WHERE station = %s AND status = 'received' AND docstatus = 1""",
		(station,),
	)
	total_received = received[0][0] if received else 0

	by_fuel_type = frappe.db.sql(
		"""SELECT fuel_type, COALESCE(SUM(received_quantity), 0) AS total
		FROM `tabDelivery`
		WHERE station = %s AND status = 'received' AND docstatus = 1
		GROUP BY fuel_type""",
		(station,),
		as_dict=True,
	)

	return {
		"station": station,
		"station_name": _station_name(station),
		"total_received": total_received,
		"by_fuel_type": [{"fuel_type": r.fuel_type, "total": float(r.total or 0)} for r in by_fuel_type],
	}


def monthly_shipments_report(station=None, year=None, month=None):
	"""Monthly shipment report for a station.

	Shows scheduled shipments and deliveries, tracking delivered, undelivered,
	and transit/extra shipments for marketing company reconciliations.
	"""
	if not station:
		station = scoped_station()
	if not station:
		st = frappe.get_all("Station", filters={"status": "active"}, limit=1, pluck="name")
		if st:
			station = st[0]
	if not station:
		frappe.throw("Station required")

	from frappe.utils import now_datetime
	import calendar
	now = now_datetime()
	year = cint(year) or now.year
	month = cint(month) or now.month

	last_day = calendar.monthrange(year, month)[1]
	start = getdate("{}-{:02d}-01".format(year, month))
	end = getdate("{}-{:02d}-{:02d}".format(year, month, last_day))

	schedules = frappe.get_all(
		"Shipment Schedule",
		filters=[
			["station", "=", station],
			["expected_shipping_date", ">=", str(start)],
			["expected_shipping_date", "<=", str(end)],
		],
		fields=[
			"name", "invoice_number", "expected_shipping_date", "fuel_type",
			"quantity", "status", "delivery", "unit_price", "total_amount", "serial_number",
		],
		order_by="expected_shipping_date asc",
	)

	deliveries = frappe.get_all(
		"Delivery",
		filters=[
			["station", "=", station],
			["order_date", ">=", str(start)],
			["order_date", "<=", str(end)],
		],
		fields=[
			"name", "invoice_number", "arrival_date", "order_date", "scheduled_date",
			"fuel_type", "tank", "expected_quantity", "received_quantity",
			"status", "is_unscheduled",
		],
		order_by="order_date asc",
	)

	tank_names = {}
	for d in deliveries:
		if d.tank and d.tank not in tank_names:
			tank_names[d.tank] = frappe.db.get_value("Tank", d.tank, "tank_name") or d.tank

	delivery_by_name = {d.name: d for d in deliveries}
	matched_delivery_names = set()

	rows = []
	for s in schedules:
		deliv = delivery_by_name.get(s.delivery) if s.delivery else None
		if deliv:
			matched_delivery_names.add(deliv.name)

		flag = ""
		if s.status == "undelivered":
			flag = "undelivered"
		elif s.status == "transit":
			flag = "transit"
		elif deliv and deliv.is_unscheduled:
			flag = "مرحلة"

		delivery_date = str(deliv.arrival_date) if deliv and deliv.arrival_date else ("—" if s.status != "delivered" else str(s.expected_shipping_date))
		tank = tank_names.get(deliv.tank, deliv.tank or "—") if deliv else "—"
		recv_qty = float(deliv.received_quantity or 0) if deliv else (float(s.quantity or 0) if s.status == "delivered" else 0)

		rows.append({
			"invoice_number": s.invoice_number or "—",
			"scheduled_date": str(s.expected_shipping_date or "—"),
			"delivery_date": delivery_date,
			"fuel_type": s.fuel_type or "—",
			"tank": tank,
			"expected_quantity": float(s.quantity or 0),
			"received_quantity": recv_qty,
			"status": s.status,
			"flag": flag,
		})

	for d in deliveries:
		if d.name not in matched_delivery_names:
			flag = "مرحلة" if d.is_unscheduled else ("undelivered" if d.status == "undelivered" else ("transit" if d.status == "transit" else ""))
			rows.append({
				"invoice_number": d.invoice_number or "—",
				"scheduled_date": str(d.scheduled_date or d.order_date or "—"),
				"delivery_date": str(d.arrival_date or "—"),
				"fuel_type": d.fuel_type or "—",
				"tank": tank_names.get(d.tank, d.tank or "—"),
				"expected_quantity": float(d.expected_quantity or 0),
				"received_quantity": float(d.received_quantity or 0),
				"status": d.status,
				"flag": flag,
			})

	total_sched = len(rows)
	total_deliv = sum(1 for r in rows if r["status"] in ("delivered", "received"))
	total_undeliv = sum(1 for r in rows if r["status"] == "undelivered" or r["flag"] == "undelivered")
	total_transit = sum(1 for r in rows if r["status"] == "transit" or r["flag"] in ("transit", "مرحلة"))
	total_qty = sum(r["received_quantity"] for r in rows)

	return {
		"station": station,
		"station_name": _station_name(station),
		"year": year,
		"month": month,
		"total_scheduled": total_sched,
		"total_delivered": total_deliv,
		"total_undelivered": total_undeliv,
		"total_transit": total_transit,
		"total_quantity_received": total_qty,
		"shipments": rows,
	}


