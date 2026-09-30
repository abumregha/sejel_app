# Dashboard-station endpoint — data contract in docs/DASHBOARD_REDESIGN_PROMPT.md §23.
#
# Design rules enforced here:
# - Backend is the ONLY source of financial truth (§27): liters, prices, expected
#   sales, collections, difference and profit all come from stored documents
#   (Reconciliation, Meter Reading, Cash Collection, Voucher, POS Record, Expense,
#   Fuel Price). The SPA may format values but never recompute money.
# - Supervisor scoping (§3.1): a user bound to a Station can only fetch that
#   station — a requested foreign station_id is rejected, not silently swapped.
# - One request returns the whole payload: tree, tanks, shifts, KPIs, alerts,
#   readings (§24). No per-meter/per-tank calls from the SPA.
# - Tank thresholds are computed in exactly ONE place (here) so the SPA never
#   re-derives status (§12).

import frappe
from frappe import _
from frappe.exceptions import DoesNotExistError, PermissionError
from frappe.utils import now, today, add_days, getdate


def _station_scoped_id(requested=None):
	"""Resolve the station id, enforcing the supervisor binding.

	Returns (station_id, role, error). error is a frappe.throw on violation.
	"""
	user_doc = frappe.get_doc("User", frappe.session.user)
	role = "supervisor"
	for r in user_doc.roles:
		if "Sejel Manager" in r.role:
			role = "manager"
			break
		elif "Sejel Finance" in r.role:
			role = "finance"
			break
		elif "Sejel Supervisor" in r.role:
			role = "supervisor"
			break
		elif r.role == "System Manager":
			role = "admin"
			break

	bound = getattr(user_doc, "sejel_station", None) or None
	if bound:
		if requested and requested != bound:
			frappe.throw(_("غير مصرح لك بعرض بيانات محطة أخرى"), PermissionError)
		return bound, role, None
	return requested or None, role, None


def _tank_status(current_level, capacity):
	"""Single source of tank thresholds (prompt §12): empty/full/normal/low/critical."""
	if capacity <= 0:
		return "critical"
	pct = (current_level or 0) / capacity * 100
	if pct <= 1:
		return "empty"
	if pct >= 98:
		return "full"
	if pct < 10:
		return "critical"
	if pct < 20:
		return "low"
	return "normal"


def _fuel_prices(date):
	"""Latest active Fuel Price per fuel type as of `date` (selling + cost)."""
	rows = frappe.get_all(
		"Fuel Price",
		filters={"is_active": 1, "effective_date": ["<=", date]},
		fields=["fuel_type", "selling_price", "cost_per_liter", "profit_margin"],
		order_by="effective_date asc",
	)
	prices = {}
	for r in rows:  # later effective_date wins
		prices[r.fuel_type] = {
			"selling_price": r.selling_price or 0,
			"cost_per_liter": r.cost_per_liter or None,
			"profit_margin": r.profit_margin or None,
		}
	return prices


@frappe.whitelist(allow_guest=True)
def dashboard_station():
	"""GET /api/dashboard-station/?station=&date= — full station payload.

	No station param + unbound user => aggregated multi-station dashboard.
	"""
	frappe.only_for(["System Manager", "Sejel Manager", "Sejel Finance", "Sejel Supervisor"])

	requested = frappe.form_dict.get("station") or None
	date = frappe.form_dict.get("date") or today()
	station_id, role, _scope_err = _station_scoped_id(requested)

	if station_id:
		if not frappe.db.exists("Station", station_id):
			frappe.throw(_("المحطة غير موجودة"), DoesNotExistError)
		payload = _single_station_payload(station_id, date, role)
	else:
		payload = _aggregate_payload(date, role)

	payload["meta"] = {
		"role": role,
		"date": date,
		"generated_at": now(),
		"bound_station": getattr(frappe.get_doc("User", frappe.session.user), "sejel_station", None) or None,
	}
	return payload


# ---------------------------------------------------------------- single station


def _single_station_payload(sid, date, role):
	station = frappe.db.get_value(
		"Station", sid,
		["name", "station_name", "address", "status", "cash_collection_mode", "day_close_time"],
		as_dict=True,
	)

	islands = frappe.get_all(
		"Island", filters={"station": sid}, fields=["name", "island_name", "number", "status"],
		order_by="number asc, creation asc",
	)
	machines = frappe.get_all(
		"Machine", filters={"station": sid},
		fields=["name", "machine_name", "island", "number"],
		order_by="island asc, number asc, creation asc",
	)
	meters = frappe.get_all(
		"Meter", filters={"machine": ["in", [m.name for m in machines]] or [""]},
		fields=["name", "meter_code", "machine", "fuel_type", "tank", "current_reading", "status"],
		order_by="meter_code asc",
	)

	# ---- today's readings (latest per meter) ---------------------------------
	reading_rows = frappe.get_all(
		"Meter Reading",
		filters={"shift": ["in", _shift_names(sid, date)]},
		fields=["name", "shift", "meter", "attendant", "start_reading", "end_reading",
			"liters_sold", "photo", "exception_type", "exception_authorized_by",
			"notes", "source", "recorded_at"],
		order_by="recorded_at desc, creation desc",
	)
	latest_by_meter = {}
	for r in reading_rows:
		latest_by_meter.setdefault(r.meter, r)

	# ---- shifts ---------------------------------------------------------------
	shifts = frappe.get_all(
		"Shift",
		filters={"station": sid, "date": date},
		fields=["name", "shift_name", "definition", "employee", "status", "is_day_close", "start_time", "end_time"],
		order_by="creation asc",
	)

	# ---- reconciliation (money source of truth) --------------------------------
	rec = frappe.db.get_value(
		"Reconciliation",
		filters={"station": sid, "status": ["!=", "cancelled"]},
		fieldname=["name", "shift", "total_liters", "expected_sales", "total_cash",
			"total_vouchers", "total_pos", "total_collection", "total_expenses",
			"net_cash", "difference", "difference_type", "status"],
		order_by="creation desc",
		as_dict=True,
	)

	# ---- expenses for the date -------------------------------------------------
	total_expenses = frappe.db.sql(
		"""SELECT COALESCE(SUM(amount), 0) FROM `tabExpense`
		WHERE station = %s AND DATE(creation) = %s""",
		(sid, date),
	)[0][0] or 0

	# ---- tanks -----------------------------------------------------------------
	tanks = frappe.get_all(
		"Tank", filters={"station": sid},
		fields=["name", "tank_name", "fuel_type", "capacity", "current_level",
			"dedicated_to_machine", "last_reading_date"],
		order_by="tank_name asc",
	)
	fuels = sorted({t.fuel_type for t in tanks if t.fuel_type})
	prices = _fuel_prices(date)

	tank_payload = []
	for t in tanks:
		pct = round((t.current_level or 0) / t.capacity * 100, 1) if t.capacity else 0
		tank_payload.append({
			"id": t.name,
			"name": t.tank_name or t.name,
			"fuel_type": t.fuel_type,
			"capacity": t.capacity,
			"current_level": t.current_level or 0,
			"percent": pct,
			"status": _tank_status(t.current_level, t.capacity),
			"last_reading_date": t.last_reading_date,
			"unit_price": prices.get(t.fuel_type, {}).get("selling_price"),
		})

	# ---- meters enriched with today's reading ------------------------------------
	meter_payload = []
	for m in meters:
		mach = next((x for x in machines if x.name == m.machine), None)
		rd = latest_by_meter.get(m.name)
		meter_payload.append({
			"id": m.name,
			"meter_code": m.meter_code,
			"machine": m.machine,
			"machine_name": (mach.machine_name if mach else None),
			"island": (mach.island if mach else None),
			"fuel_type": m.fuel_type,
			"tank": m.tank,
			"current_reading": m.current_reading,
			"status": m.status,
			"reading": {
				"start_reading": rd.start_reading if rd else None,
				"end_reading": rd.end_reading if rd else None,
				"liters_sold": (rd.liters_sold if rd else None),
				"attendant": (rd.attendant if rd else None),
				"photo": rd.photo if rd else None,
				"exception_type": rd.exception_type if rd else None,
				"exception_authorized_by": rd.exception_authorized_by if rd else None,
				"notes": rd.notes if rd else None,
				"source": rd.source if rd else None,
				"recorded_at": rd.recorded_at if rd else None,
				"unit_price": prices.get(m.fuel_type, {}).get("selling_price"),
				"expected_sales": (
					round((rd.liters_sold or 0) * prices[m.fuel_type]["selling_price"], 2)
					if rd and m.fuel_type in prices else None
				),
			} if rd else None,
		})

	# ---- island/machine tree ------------------------------------------------------
	tree = []
	for isl in islands:
		mach_list = [m for m in machines if m.island == isl.name]
		tree.append({
			"id": isl.name,
			"name": isl.island_name or f"جزيرة {isl.number or ''}".strip(),
			"number": isl.number,
			"status": isl.status,
			"machines": [{
				"id": m.name,
				"name": m.machine_name or f"مضخة {m.number or ''}".strip(),
				"number": m.number,
				"meters": [x for x in meter_payload if x["machine"] == m.name],
			} for m in mach_list],
		})

	# ---- alerts (server-computed, single rule set) ---------------------------------
	alerts = []
	for t in tank_payload:
		if t["status"] in ("low", "critical", "empty"):
			level = {"low": "منخفض", "critical": "حرج", "empty": "فارغ"}[t["status"]]
			severity = {"low": "warning", "critical": "critical", "empty": "critical"}[t["status"]]
			alerts.append({
				"type": "tank_level", "severity": severity,
				"message": f"الخزان {t['name']} ({t['fuel_type']}) — المستوى {level} ({t['percent']}%)",
				"link": f"/app/tanks/{t['id']}",
			})
	for m in meter_payload:
		if m["reading"] and m["reading"].get("exception_type"):
			alerts.append({
				"type": "meter_exception", "severity": "warning",
				"message": f"استثناء في العداد {m['meter_code']} — {m['reading']['exception_type']}",
				"link": f"/app/meters/{m['id']}",
			})
		elif not m["reading"] and m["status"] != "inactive":
			alerts.append({
				"type": "missing_reading", "severity": "warning",
				"message": f"لا توجد قراءة لعداد {m['meter_code']} اليوم",
				"link": f"/app/meters/{m['id']}",
			})
	# Employee shifts only — the day-close container is the readings/closing
	# cycle, not someone's working shift, so it must not raise this alert.
	unclosed = [s for s in shifts if s.status in ("open", "in_progress") and not s.is_day_close]
	if unclosed:
		alerts.append({
			"type": "shift_open", "severity": "info",
			"message": f"{len(unclosed)} مناوبة مفتوحة لم تُغلق بعد",
			"link": "/app/shifts",
		})
	if rec and rec.status == "submitted":
		alerts.append({
			"type": "reconciliation_pending", "severity": "info",
			"message": "مطابقة مناوبة بانتظار المراجعة المالية",
			"link": f"/app/reconciliations/{rec.name}",
		})

	# ---- KPIs -----------------------------------------------------------------------
	today_liters = sum(
		(r.liters_sold or 0) for r in latest_by_meter.values() if r.liters_sold
	)
	total_capacity = sum(t.capacity or 0 for t in tanks)
	current_volume = sum(t.current_level or 0 for t in tanks)

	kpis = {
		"total_liters": today_liters,
		"expected_sales": (rec.expected_sales if rec else None),
		"total_collection": (rec.total_collection if rec else None),
		"total_cash": (rec.total_cash if rec else None),
		"total_vouchers": (rec.total_vouchers if rec else None),
		"total_pos": (rec.total_pos if rec else None),
		"difference": (rec.difference if rec else None),
		"difference_type": (rec.difference_type if rec else None),
		"total_expenses": total_expenses,
		"net_cash": (rec.net_cash if rec else None),
		"profit": _profit_from_reconciliation(rec, prices),
		"reconciliation_id": (rec.name if rec else None),
		"reconciliation_status": (rec.status if rec else None),
	}

	return {
		"mode": "station",
		"station": {
			"id": station.name,
			"name": station.station_name or station.name,
			"address": station.address,
			"status": station.status,
			"cash_collection_mode": station.cash_collection_mode,
			"day_close_time": station.day_close_time,
		},
		"islands": tree,
		"trend": _trend_series(sid, date),
		"tanks": tank_payload,
		"meters": meter_payload,
		"shifts": [{
			"id": s.name, "name": s.shift_name, "definition": s.definition,
			"employee": s.employee, "status": s.status,
			"is_day_close": bool(s.is_day_close),
			"start_time": s.start_time, "end_time": s.end_time,
		} for s in shifts],
		"kpis": kpis,
		"readings_status": {
			"total": len(meter_payload),
			"done": sum(1 for m in meter_payload if m["status"] == "active" and m["reading"]),
			"pending": sum(1 for m in meter_payload if m["status"] == "active" and not m["reading"]),
			"exceptions": sum(1 for m in meter_payload if m["reading"] and m["reading"].get("exception_type")),
		},
		"alerts": alerts,
		"summary": {
			"total_capacity": total_capacity,
			"current_volume": current_volume,
			"tanks_count": len(tanks),
			"meters_count": len(meters),
		},
	}


def _trend_series(sid, date, days=14):
	"""Daily trend for the dashboard charts: parallel arrays over the last
	`days` days ending `date` (inclusive), from Reconciliation joined to Shift
	(the money source of truth). Empty arrays when no history exists — the SPA
	renders an empty-state, never fake data.
	"""
	start = add_days(getdate(date), -(days - 1))
	rows = frappe.db.sql(
		"""SELECT s.date AS d,
			SUM(r.total_liters) AS liters,
			SUM(r.expected_sales) AS expected_sales,
			SUM(r.total_collection) AS collection,
			SUM(r.difference) AS difference
		FROM `tabReconciliation` r
		JOIN `tabShift` s ON s.name = r.shift
		WHERE r.station = %s AND s.date >= %s AND s.date <= %s
		GROUP BY s.date ORDER BY s.date ASC""",
		(sid, start, getdate(date)),
		as_dict=True,
	)
	by_day = {str(r.d): r for r in rows}
	labels, liters, expected, collection, difference = [], [], [], [], []
	d = getdate(start)
	for _ in range(days):
		key = str(d)
		r = by_day.get(key)
		labels.append(key)
		liters.append(float(r.liters or 0) if r else 0)
		expected.append(float(r.expected_sales or 0) if r else 0)
		collection.append(float(r.collection or 0) if r else 0)
		difference.append(float(r.difference or 0) if r else 0)
		if r is None:
			# keep only days that have data? No — a continuous axis reads better;
			# zeros are truthful (station closed / nothing closed that day).
			pass
		d = add_days(d, 1)
	return {
		"labels": labels,
		"liters": liters,
		"expected_sales": expected,
		"collection": collection,
		"difference": difference,
		"has_data": bool(rows),
	}


def _profit_from_reconciliation(rec, prices):
	"""هامش الربح (prompt §4): (selling − cost) × liters, per fuel summary rows.

	Returns None when cost data is missing — the SPA shows 'غير مُعرّف'.
	"""
	if not rec:
		return None
	rows = frappe.get_all(
		"Shift Fuel Summary", filters={"reconciliation": rec.name},
		fields=["fuel_type", "liters_sold"],
	)
	profit = 0.0
	any_cost = False
	for r in rows:
		p = prices.get(r.fuel_type)
		if p and p["cost_per_liter"] is not None:
			profit += (p["selling_price"] - p["cost_per_liter"]) * (r.liters_sold or 0)
			any_cost = True
	return round(profit, 2) if any_cost else None


def _shift_names(sid, date):
	return frappe.get_all("Shift", filters={"station": sid, "date": date}, pluck="name") or [""]


# ---------------------------------------------------------------- aggregate mode


def _aggregate_payload(date, role):
	stations = frappe.get_all(
		"Station", filters={"status": "active"},
		fields=["name", "station_name", "address"],
		order_by="station_name asc",
	)
	out = []
	for s in stations:
		shifts_today = frappe.db.count("Shift", {"station": s.name, "date": date})
		open_now = frappe.db.count(
			"Shift", {"station": s.name, "date": date, "status": ["in", ["open", "in_progress"]]}
		)
		tanks = frappe.get_all(
			"Tank", filters={"station": s.name},
			fields=["capacity", "current_level"],
		)
		total_cap = sum(t.capacity or 0 for t in tanks)
		cur_vol = sum(t.current_level or 0 for t in tanks)
		low = sum(1 for t in tanks if _tank_status(t.current_level, t.capacity) in ("low", "critical", "empty"))
		kpis = frappe.db.get_value(
			"Reconciliation",
			filters={"station": s.name, "status": ["!=", "cancelled"]},
			fieldname=["total_liters", "expected_sales", "total_collection", "difference", "difference_type"],
			order_by="creation desc",
			as_dict=True,
		) or {}
		out.append({
			"id": s.name,
			"name": s.station_name or s.name,
			"address": s.address,
			"open_shifts": open_now,
			"shifts_today": shifts_today,
			"tanks": len(tanks),
			"low_tanks": low,
			"volume_pct": round(cur_vol / total_cap * 100, 1) if total_cap else 0,
			"total_liters": kpis.get("total_liters"),
			"expected_sales": kpis.get("expected_sales"),
			"total_collection": kpis.get("total_collection"),
			"difference": kpis.get("difference"),
			"difference_type": kpis.get("difference_type"),
		})

	return {
		"mode": "aggregate",
		"stations": out,
		"alerts": [],
		"date": date,
	}
