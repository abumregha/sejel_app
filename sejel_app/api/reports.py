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

