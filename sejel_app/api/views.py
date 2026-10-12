import frappe
import json
from frappe import _
from .crud import get_list, get_doc, create_doc, update_doc, delete_doc
from .scoping import apply_to_filters, check_station, check_station_payload, explicit_station_filter, scoped_station
from . import reports as reports_mod

# Frappe internal params to strip from filters
SKIP_PARAMS = {"cmd", "resource", "user", "sid", "device", "type"}

# URL slug → (DocType, list fields)
RESOURCES = {
	"stations": ("Station", ["name", "station_name", "address", "status", "relationship_type", "marketing_company", "day_close_time", "modified"]),
	"islands": ("Island", ["name", "island_name", "station", "number", "status", "modified"]),
	"machines": ("Machine", ["name", "machine_name", "island", "station", "number", "modified"]),
	"meters": ("Meter", ["name", "meter_code", "machine", "fuel_type", "tank", "current_reading", "status", "modified"]),
	"tanks": ("Tank", ["name", "tank_name", "station", "fuel_type", "capacity", "current_level", "last_reading_date", "modified"]),
	"fuel-types": ("Fuel Type", ["name", "fuel_name", "fuel_name_en", "is_active", "modified"]),
	"fuel-prices": ("Fuel Price", ["name", "fuel_type", "selling_price", "profit_margin", "cost_per_liter", "effective_date", "is_active", "modified"]),
	"marketing-companies": ("Marketing Company", ["name", "company_name", "company_name_en", "modified"]),
	"employees": ("Employee", ["name", "employee_name", "station", "phone", "status", "modified"]),
	"shift-definitions": ("Shift Definition", ["name", "definition_name", "station", "island", "start_time", "end_time", "days", "is_active", "modified"]),
	"shifts": ("Shift", ["name", "shift_name", "station", "definition", "employee", "island", "date", "start_time", "end_time", "is_day_close", "status", "modified"]),
	"reading-deletion-logs": ("Reading Deletion Log", ["name", "reading", "meter", "meter_code",
		"station", "station_name", "shift", "shift_date", "recorded_at", "start_reading",
		"end_reading", "liters_sold", "is_opening", "exception_type", "notes", "deleted_by",
		"deleted_at", "modified"]),
	"meter-readings": ("Meter Reading", ["name", "shift", "meter", "attendant", "start_reading", "end_reading", "liters_sold", "is_opening", "exception_type", "exception_authorized_by", "notes", "source", "recorded_at", "modified"]),
	"cash-collections": ("Cash Collection", ["name", "shift", "amount", "time", "received_by", "is_cancelled", "modified"]),
	"vouchers": ("Voucher", ["name", "shift", "category", "count", "total_value", "is_cancelled", "modified"]),
	"pos-records": ("POS Record", ["name", "shift", "total_amount", "transaction_count", "is_cancelled", "modified"]),
	"expenses": ("Expense", ["name", "station", "shift", "category", "amount", "description", "status", "payment_method", "expense_date", "modified"]),
	"expense-categories": ("Expense Category", ["name", "category_name", "station", "is_active", "modified"]),
	"voucher-settlements": ("Voucher Settlement", ["name", "station", "submission_date", "total_value", "total_count", "denom_5", "denom_6", "denom_7", "denom_8", "status", "paid_amount", "modified"]),
	"reconciliations": ("Reconciliation", ["name", "shift", "station", "total_liters", "expected_sales", "total_cash", "total_vouchers", "total_pos", "total_collection", "total_expenses", "net_cash", "difference", "difference_type", "status", "modified"]),
	"shift-fuel-summaries": ("Shift Fuel Summary", ["name", "reconciliation", "fuel_type", "liters_sold", "unit_price", "expected_sales", "modified"]),
	"deliveries": ("Delivery", ["name", "station", "fuel_type", "supplier", "expected_quantity", "received_quantity", "shortage", "invoice_number", "payment_status", "status", "order_date", "modified"]),
	"delivery-requests": ("Delivery Request", ["name", "station", "fuel_type", "requested_quantity", "priority", "status", "expected_delivery_date", "modified"]),
	"tank-readings": ("Tank Reading", ["name", "tank", "reading_level", "reading_type", "recorded_at", "recorded_by", "notes", "modified"]),
	"tank-transfers": ("Tank Transfer", ["name", "station", "from_tank", "to_tank", "fuel_type", "quantity", "reason", "status", "transfer_date", "modified"]),
	"fuel-reconciliations": ("Fuel Reconciliation", ["name", "tank", "station", "date", "received_quantity", "transferred_in", "transferred_out", "sold_quantity", "theoretical_level", "actual_level", "variance", "variance_type", "status", "modified"]),
	"shortage-claims": ("Shortage Claim", ["name", "delivery", "shortage_amount", "notes", "status", "claim_date", "settlement_date", "modified"]),
	"voucher-categories": ("Voucher Category", ["name", "category_name", "value", "is_active", "modified"]),
	"users": ("User", ["name", "username", "first_name", "last_name", "email", "enabled", "sejel_station", "modified"]),
}


def _get_resource():
	return frappe.request.args.get("resource") or ""


def _get_name():
	return frappe.get_request_header("X-Doc-Name") or frappe.request.args.get("name") or ""


def _get_filters(doctype=None):
	"""Query-string filters for the generic list endpoint.

	`?filters={"field": "value"}` (JSON) is the documented SPA contract. Any
	other query parameter is transport noise, not a filter: passing them
	straight through to get_list() made the endpoint raise UndefinedColumn for
	anything that is not a real column — e.g. `?station=` on Meter Reading,
	which has no station field (QA-5).

	The pagination/ordering keys are still returned so crud_list can pop them.
	Unknown keys are dropped rather than 500ing the whole list.
	"""
	args = dict(frappe.request.args or {})
	filters = {}

	raw = args.pop("filters", None)
	if raw:
		try:
			parsed = json.loads(raw)
		except (TypeError, ValueError):
			frappe.throw(_("مرشح filters يجب أن يكون JSON صالحاً"))
		if not isinstance(parsed, dict):
			frappe.throw(_("مرشح filters يجب أن يكون كائن JSON"))
		filters.update({k: v for k, v in parsed.items() if v not in (None, "")})

	# control params — consumed by crud_list, never sent as filters
	for key in ("limit_page_length", "offset", "order_by"):
		if key in args:
			filters[key] = args.pop(key)

	ignored = []
	for key, value in args.items():
		if key in SKIP_PARAMS:
			continue
		if key == "station" and doctype and not _is_queryable_field(doctype, key):
			# `?station=` on a doctype that reaches its station through a parent
			# (Meter Reading / Cash Collection / Voucher / POS Record all hang off
			# Shift) was previously DROPPED as an unknown column. The caller then
			# got every row in the site while the response looked filtered — the
			# exact defect behind the 2026-10-03 loss of all 32 Meter Readings.
			# Honour the filter instead of discarding it.
			translated = explicit_station_filter(doctype, value)
			if translated:
				filters.update(translated)
				continue
		if doctype and not _is_queryable_field(doctype, key):
			# Unknown column: ignore rather than blow up the whole list — but
			# RECORD it. Silently dropping a filter returns the caller every
			# row of the table while it looks filtered, which is how a
			# "show me this station" query turns into "here is everything"
			# (2026-10-03 incident: readings of every station were deleted
			# because `?station=` had been dropped from the query).
			ignored.append(key)
			continue
		filters[key] = value

	if ignored:
		filters["_ignored_filters"] = ignored

	return filters


def _is_queryable_field(doctype, fieldname):
	"""True when `fieldname` is a real field of `doctype` (or a link target)."""
	meta = frappe.get_meta(doctype)
	if meta.has_field(fieldname):
		return True
	# Link fields are also filterable by the name of the linked document.
	return any(f.fieldtype == "Link" and f.fieldname == fieldname for f in meta.fields)


def _get_body():
	return json.loads(frappe.request.data or "{}")


def _decorate_users(rows):
	"""Add the SPA-facing `role` (admin/manager/finance/supervisor) to User rows
	from their Has Role children — Frappe stores roles on child docs, and the
	generic list endpoint can only return flat fields."""
	names = [r.get("name") for r in rows if r.get("name")]
	role_map = {}
	if names:
		for hr in frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "parent": ["in", names]},
			fields=["parent", "role"],
		):
			role_map.setdefault(hr.parent, []).append(hr.role)
	for r in rows:
		roles = role_map.get(r.get("name"), [])
		r["role"] = (
			"admin" if "System Manager" in roles
			else "manager" if "Sejel Manager" in roles
			else "finance" if "Sejel Finance" in roles
			else "supervisor" if "Sejel Supervisor" in roles
			else None
		)
		r.setdefault("username", r.get("name"))


ROLE_TO_FRAPPE = {
	"admin": ["System Manager", "Sejel Manager", "Sejel Supervisor", "Sejel Finance"],
	"manager": ["Sejel Manager"],
	"finance": ["Sejel Finance"],
	"supervisor": ["Sejel Supervisor"],
}


def _apply_user_extras(doc, data):
	"""Map the SPA's flat user payload onto User + role children."""
	roles = ROLE_TO_FRAPPE.get(data.get("role"), ["Sejel Supervisor"])
	doc.set("roles", [])
	for r in roles:
		doc.append("roles", {"role": r})
	if "station" in data:
		doc.sejel_station = data.get("station") or None


def _create_user(data):
	if not data.get("email"):
		# User.email is mandatory in Frappe — synthesize from username
		data["email"] = "{}@sejel.ly".format(data.get("username") or "user")
	doc = frappe.new_doc("User")
	doc.update({
		"email": data["email"],
		"first_name": data.get("first_name") or data.get("username") or "",
		"last_name": data.get("last_name") or "",
		"username": data.get("username") or None,
		"enabled": 1,
	})
	if data.get("password"):
		doc.new_password = data["password"]
	_apply_user_extras(doc, data)
	doc.insert()
	return doc


def _update_user(name, data):
	doc = frappe.get_doc("User", name)
	for f in ("first_name", "last_name", "username"):
		if f in data:
			doc.set(f, data[f])
	if data.get("password"):
		doc.new_password = data["password"]
	if "enabled" in data:
		doc.enabled = 1 if data["enabled"] else 0
	if "role" in data:
		_apply_user_extras(doc, data)
	elif "station" in data:
		doc.sejel_station = data.get("station") or None
	doc.save()
	return doc


@frappe.whitelist()
def _enrich_shortage_claims(rows):
	"""Shortage claims showed NaN and blank columns because the screens read
	fields the list endpoint never returned (QA-20). Return the human-facing
	values the operator needs rather than raw document hashes."""
	if not rows:
		return
	delivery_ids = {r.get("delivery") for r in rows if r.get("delivery")}
	deliveries = {}
	if delivery_ids:
		for d in frappe.get_all(
			"Delivery",
			filters={"name": ["in", list(delivery_ids)]},
			fields=["name", "station", "invoice_number"],
		):
			deliveries[d.name] = d
	station_names = {}
	for name in {d.station for d in deliveries.values() if d.station}:
		station_names[name] = frappe.db.get_value("Station", name, "station_name") or name
	for r in rows:
		d = deliveries.get(r.get("delivery"))
		r["station_name"] = station_names.get(d.station) if d else None
		r["claimed_quantity"] = r.get("shortage_amount")
		r["delivery_id_display"] = (d.invoice_number if d else None) or r.get("delivery")
		r["description"] = r.get("notes")


def _enrich_fuel_reconciliations(rows):
	"""«تسوية الوقود» read station_name / tank_name but the endpoint returned
	only the raw link codes, so both columns rendered empty (QA-23)."""
	if not rows:
		return
	station_names = {}
	for name in {r.get("station") for r in rows if r.get("station")}:
		station_names[name] = frappe.db.get_value("Station", name, "station_name") or name
	tank_names = {}
	for name in {r.get("tank") for r in rows if r.get("tank")}:
		tank_names[name] = frappe.db.get_value("Tank", name, "tank_name") or name
	for r in rows:
		r["station_name"] = station_names.get(r.get("station"))
		r["tank_name"] = tank_names.get(r.get("tank"))


def _enrich_meters(rows):
	if not rows:
		return
	counts = {}
	names = [r.get("name") for r in rows if r.get("name")]
	if names:
		for c in frappe.get_all(
			"Meter Reading",
			filters={"meter": ["in", names]},
			fields=["meter", "count(name) as reading_count"],
			group_by="meter",
		):
			counts[c.meter] = int(c.reading_count or 0)
	for r in rows:
		r["reading_count"] = counts.get(r.get("name"), 0)


LIST_ENRICHERS = {
	"shortage-claims": _enrich_shortage_claims,
	"fuel-reconciliations": _enrich_fuel_reconciliations,
	"meters": _enrich_meters,
}


@frappe.whitelist()
def crud_list(**kwargs):
	resource = _get_resource()
	if resource not in RESOURCES:
		frappe.throw("Unknown resource: " + resource)
	doctype, fields = RESOURCES[resource]

	if frappe.request.method == "GET":
		filters = _get_filters(doctype)
		ignored_filters = filters.pop("_ignored_filters", [])
		filters = apply_to_filters(doctype, filters)  # station-bound users: own station only
		limit = int(filters.pop("limit_page_length", 0) or 0)
		offset = int(filters.pop("offset", 0) or 0)
		order_by = filters.pop("order_by", None)
		result = get_list(doctype, fields=fields, filters=filters or None, limit_page_length=limit, offset=offset, order_by=order_by)
		if ignored_filters:
			# Tell the caller which of its filters were dropped instead of
			# handing back an unfiltered list as if it were filtered.
			result["ignored_filters"] = ignored_filters
		if resource == "users":
			_decorate_users(result["results"])
		elif resource in LIST_ENRICHERS:
			LIST_ENRICHERS[resource](result["results"])
		return result
	else:
		body = _get_body()
		if resource == "users":
			return _create_user(body)
		# reads guard the document that exists; this guards the one being made
		check_station_payload(doctype, body)
		return create_doc(doctype, body)


@frappe.whitelist()
def crud_detail(**kwargs):
	resource = _get_resource()
	name = _get_name()
	if resource not in RESOURCES:
		frappe.throw("Unknown resource: " + resource)
	doctype, fields = RESOURCES[resource]

	if frappe.request.method == "GET":
		check_station(doctype, name)
		out = get_doc(doctype, name)
		if resource == "users":
			_decorate_users([out])
			out["station_id"] = out.get("sejel_station")
		return out
	elif frappe.request.method in ("PUT", "PATCH"):
		# PATCH = partial update (same semantics here: only provided fields are applied)
		check_station(doctype, name)
		body = _get_body()
		check_station_payload(doctype, body)  # may not move a doc into another station
		if resource == "users":
			return _update_user(name, body)
		return update_doc(doctype, name, body)
	elif frappe.request.method == "DELETE":
		check_station(doctype, name)
		return delete_doc(doctype, name)


@frappe.whitelist()
def close_shift(name):
	check_station("Shift", name)
	shift = frappe.get_doc("Shift", name)
	shift.close_shift()
	return {"ok": True, "status": shift.status}


@frappe.whitelist()
def ensure_day_close():
	"""POST /api/ensure-day-close/ — idempotently return today's day-close
	Shift for a station, creating it only if none exists.

	Root-cause fix (client report 2026-10-01): the SPA decided "no day-close
	container yet" from a dashboard payload that can be seconds stale — every
	failed/slow save then created ANOTHER "إقفال يوم <date>" Shift (8 duplicates
	observed on one test station). Server-side check-then-create inside one
	request can't race the UI's stale list.
	"""
	body = {}
	try:
		body = json.loads(frappe.request.data or "{}")
	except Exception:
		pass
	station = body.get("station") or frappe.form_dict.get("station")
	date = body.get("date") or frappe.form_dict.get("date") or frappe.utils.today()
	if not station:
		frappe.throw(_("يرجى تحديد المحطة"))
	check_station("Station", station)

	existing = frappe.get_all(
		"Shift",
		filters={
			"station": station, "date": date, "is_day_close": 1,
			"status": ["in", ["open", "in_progress", "submitted", "closed"]],
		},
		fields=["name", "status"],
		order_by="creation asc",
		limit_page_length=1,
	)
	if existing:
		s = existing[0]
		# A closed day is financially sealed. Returning it as a save target
		# would make the NEXT save create a second day-close shift and, on
		# closing it, a SECOND reconciliation for the same station/day with the
		# same figures (observed 2026-10-03 16:53 + 16:57). The caller must
		# refuse to add readings to a closed day instead.
		return {
			"ok": True,
			"created": False,
			"name": s.name,
			"status": s.status,
			"closed": s.status == "closed",
		}

	# keep the shift times consistent with the station's reading cycle —
	# the Station doc is authoritative (Frappe Time fields ignore JSON defaults,
	# so it must be read and set explicitly)
	close_t = frappe.db.get_value("Station", station, "day_close_time") or "23:00:00"
	doc = frappe.get_doc({
		"doctype": "Shift",
		"station": station,
		"shift_name": "إقفال يوم " + str(date),
		"date": date,
		# start=end is intentional: the day-close container brackets the whole
		# reading cycle (e.g. 11:00→11:00), not an employee's working window.
		"start_time": close_t,
		"end_time": close_t,
		"is_day_close": 1,
		"status": "open",
	}).insert()
	return {"ok": True, "created": True, "name": doc.name, "status": doc.status, "closed": False}


@frappe.whitelist()
def get_dashboard():
	stations = frappe.get_all("Station", filters={"status": "active"}, fields=["name"])
	total_stations = len(stations)
	total_tanks = frappe.db.count("Tank")
	open_shifts = frappe.db.count("Shift", {"status": ["in", ["open", "in_progress"]]})
	pending_deliveries = frappe.db.count("Delivery Request", {"status": "pending"})
	low_tanks = frappe.db.sql(
		"""SELECT COUNT(*) FROM tabTank WHERE current_level < capacity * 0.2""",
	)[0][0]
	return {
		"total_stations": total_stations,
		"total_tanks": total_tanks,
		"open_shifts": open_shifts,
		"pending_deliveries": pending_deliveries,
		"low_tanks": low_tanks,
	}


@frappe.whitelist()
def daily_report():
	"""Delegates to reports.daily_report — real Reconciliation aggregates."""
	return reports_mod.daily_report(frappe.form_dict.get("date"))


@frappe.whitelist()
def export_station_excel_endpoint():
	"""GET /api/export/?view=station|reconciliation|shift&name=<docname> → .xlsx"""
	return reports_mod.export_station_excel(
		frappe.form_dict.get("view") or "station",
		frappe.form_dict.get("name") or "",
	)


@frappe.whitelist()
def generate_shifts():
	"""POST /api/generate-shifts/ — auto-create today's shifts from definitions.

	Body/query: date (optional), emergency (0/1 — ignores the weekday filter),
	station (optional; scoped users are always pinned to their own).
	"""
	from .shift_gen import generate_shifts_for_date
	body = {}
	try:
		import json as _json
		body = _json.loads(frappe.request.data or "{}")
	except Exception:
		pass
	return generate_shifts_for_date(
		body.get("date") or frappe.form_dict.get("date"),
		body.get("emergency") if "emergency" in body else frappe.form_dict.get("emergency"),
	)


@frappe.whitelist()
def monthly_report():
	"""Delegates to reports.monthly_report — real per-station aggregates."""
	return reports_mod.monthly_report(
		frappe.form_dict.get("year"), frappe.form_dict.get("month")
	)


@frappe.whitelist()
def daily_sales():
	"""Site-wide cash/coupon/e-payment totals for one date, scoped to the
	caller's stations.

	Every aggregate here ran as raw SQL with no station filter (round 4,
	2026-10-03): a supervisor bound to one station could read the whole
	company's cash, and before the guest flag was removed, so could an
	unauthenticated visitor.
	"""
	date = frappe.form_dict.get("date")
	if not date:
		frappe.throw("Date required")

	mine = scoped_station()
	stations = [mine] if mine else frappe.get_all("Station", filters={"status": "active"}, pluck="name")
	if not stations:
		return {
			"cash_sales": 0, "coupon_sales": 0, "coupon_details": [],
			"epayment_sales": 0, "total_collection": 0, "total_expenses": 0,
			"net_income": 0, "stations": [],
		}

	cash_total = frappe.db.sql(
		"""SELECT COALESCE(SUM(c.amount), 0) FROM `tabCash Collection` c
		JOIN `tabShift` s ON s.name = c.shift
		WHERE DATE(c.creation) = %s AND s.station IN %s""",
		(date, tuple(stations)),
	)[0][0] or 0

	coupon_rows = frappe.db.sql(
		"""SELECT v.category, COUNT(*) as cnt, SUM(v.total_value) as total
		FROM `tabVoucher` v JOIN `tabShift` s ON s.name = v.shift
		WHERE DATE(v.creation) = %s AND s.station IN %s GROUP BY v.category""",
		(date, tuple(stations)),
		as_dict=True,
	)

	coupon_details = []
	for row in coupon_rows:
		cat_name = frappe.db.get_value("Voucher Category", row.category, "category_name") or row.category
		val = frappe.db.get_value("Voucher Category", row.category, "value") or 0
		coupon_details.append({
			"category": int(val) if val else cat_name,
			"count": row.cnt,
			"total": row.total or 0,
		})
	coupon_details.sort(key=lambda x: x.get("category", 0))

	coupon_total = sum(c["total"] for c in coupon_details)

	epayment_total = frappe.db.sql(
		"""SELECT COALESCE(SUM(p.total_amount), 0) FROM `tabPOS Record` p
		JOIN `tabShift` s ON s.name = p.shift
		WHERE DATE(p.creation) = %s AND s.station IN %s""",
		(date, tuple(stations)),
	)[0][0] or 0

	expense_total = frappe.db.sql(
		"""SELECT COALESCE(SUM(amount), 0) FROM `tabExpense`
		WHERE DATE(creation) = %s AND station IN %s""",
		(date, tuple(stations)),
	)[0][0] or 0

	total_collection = cash_total + coupon_total + epayment_total
	net_income = total_collection - expense_total

	return {
		"cash_sales": cash_total,
		"coupon_sales": coupon_total,
		"coupon_details": coupon_details,
		"epayment_sales": epayment_total,
		"total_collection": total_collection,
		"total_expenses": expense_total,
		"net_income": net_income,
		"stations": [],
	}


# ── Station Setup Wizard ─────────────────────────────────────

def _setup_station_impl(body):
	"""Atomically create a Station with islands, machines, tanks and meters.

	All documents are inserted inside one transaction; any failure rolls back
	everything so no half-configured station is ever left behind.

	body keys:
		station: {station_name, address, relationship_type, status, marketing_company}
		islands: [{machines, meters}, ...]       — per-island counts (islands may differ)
		islands_count / machines_per_island /    — legacy uniform counts, used when
		meters_per_machine                         `islands` is absent
		tanks: [{fuel_type, capacity, tank_name?}, ...]

	Raises ValidationError if a station with the same station_name already exists.
	"""
	if not isinstance(body, dict):
		frappe.throw("Invalid request body")

	station_data = body.get("station") or {}
	station_name = (station_data.get("station_name") or "").strip()
	if not station_name:
		frappe.throw("Station name is required")

	machines_per_island = int(body.get("machines_per_island") or 2)
	meters_per_machine = int(body.get("meters_per_machine") or 2)
	tanks_in = body.get("tanks") or []

	# Per-island specs (client: islands don't necessarily hold the same number
	# of pumps). Falls back to uniform counts when no spec is provided.
	islands_spec = body.get("islands") or []
	if islands_spec:
		islands_count = len(islands_spec)
		spec_machines = [max(0, min(20, int(s.get("machines", machines_per_island)))) for s in islands_spec]
		spec_meters = [max(0, min(10, int(s.get("meters", meters_per_machine)))) for s in islands_spec]
	else:
		islands_count = int(body.get("islands_count") or 2)
		spec_machines = [max(0, machines_per_island)] * islands_count
		spec_meters = [max(0, meters_per_machine)] * islands_count

	if islands_count < 0 or machines_per_island < 0 or meters_per_machine < 0:
		frappe.throw("Counts cannot be negative")
	if islands_count > 20:
		frappe.throw("Counts exceed reasonable limits (20 islands)")
	for t in tanks_in:
		if not t.get("fuel_type"):
			frappe.throw("Every tank needs a fuel type")
		if not t.get("capacity") or float(t.get("capacity")) <= 0:
			frappe.throw("Every tank needs a positive capacity")

	created = []

	try:
		frappe.db.begin()

		# Duplicate protection — Station docnames are hashes, so match on the field
		if frappe.db.exists("Station", {"station_name": station_name}):
			frappe.throw(_("يوجد محطة بنفس الاسم: {0} — اختر اسمًا آخر").format(station_name))

		# Station
		station = frappe.new_doc("Station")
		station.update({
			"station_name": station_name,
			"address": station_data.get("address") or "",
			"relationship_type": station_data.get("relationship_type") or "owned",
			"status": station_data.get("status") or "active",
			# Deterministic day-close/reading-cycle boundary (Frappe Time fields
			# would otherwise stamp the insert wall-clock; Station.validate also
			# guards this for the plain form).
			"day_close_time": station_data.get("day_close_time") or "23:00:00",
		})
		if station_data.get("marketing_company"):
			station.marketing_company = station_data["marketing_company"]
		station.insert()
		created.append(("Station", station.name))

		# Numbering continues after whatever already exists for this station
		island_start = frappe.db.count("Island", {"station": station.name}) + 1
		machine_counter = frappe.db.count(
			"Machine",
			{"station": station.name},
		)

		# Islands + Machines — counts come from the per-island spec so islands
		# can hold different numbers of pumps/meters.
		island_names = []
		machine_names = []  # (machine_name, machine_number, island_name)
		island_meter_counts = {}  # island_name -> meters per machine on this island
		number = island_start
		for i in range(islands_count):
			island = frappe.new_doc("Island")
			island.update({
				"island_name": "جزيرة {}".format(number),
				"station": station.name,
				"number": number,
			})
			island.insert()
			created.append(("Island", island.name))
			island_names.append(island.name)
			island_meter_counts[island.name] = spec_meters[i] if i < len(spec_meters) else 0

			for m in range(spec_machines[i] if i < len(spec_machines) else 0):
				machine_counter += 1
				machine = frappe.new_doc("Machine")
				machine.update({
					"machine_name": "مضخة {}".format(machine_counter),
					"island": island.name,
					"number": m + 1,
				})
				machine.insert()
				created.append(("Machine", machine.name))
				machine_names.append((machine.name, machine_counter, island.name))

			number += 1

		# Tanks (one per entry; fuel type set per tank)
		tank_names = []  # (tank_name, fuel_type)
		fuel_cycle = []
		for idx, t in enumerate(tanks_in):
			tank = frappe.new_doc("Tank")
			tank.update({
				"tank_name": t.get("tank_name") or "خزان {} ({})".format(idx + 1, t["fuel_type"]),
				"station": station.name,
				"fuel_type": t["fuel_type"],
				"capacity": t["capacity"],
				"current_level": t.get("current_level") or 0,
			})
			tank.insert()
			created.append(("Tank", tank.name))
			tank_names.append(tank.name)
			fuel_cycle.append(t["fuel_type"])

		meter_rows = []
		total_meters = sum(island_meter_counts.values())
		if total_meters > 0:
			if not tank_names:
				frappe.throw("Meters require at least one tank")

			# Meters need a globally-unique code; seed data uses M01A/M01B…
			used_codes = set(frappe.get_all("Meter", pluck="meter_code"))
			for island_name in island_names:
				meters_here = island_meter_counts.get(island_name, 0)
				if meters_here <= 0:
					continue
				island_machines = [m for m in machine_names if m[2] == island_name]
				# NOTE: do not name this `_`. It shadows the gettext `_` imported
				# above, making every `_("...")` in this function an
				# UnboundLocalError (QA-6: duplicate station name answered 500).
				for machine_name, mnum, _island_name in island_machines:
					for s in range(meters_here):
						code = "M{:02d}{}".format(mnum, chr(ord("A") + s))
						while code in used_codes:
							code += "X"
						used_codes.add(code)
						# Cycle fuel types across tanks; meter links to the
						# first tank carrying that fuel type.
						fuel_type = fuel_cycle[(s) % len(fuel_cycle)]
						tank_link = tank_names[fuel_cycle.index(fuel_type)]
						meter = frappe.new_doc("Meter")
						meter.update({
							"meter_code": code,
							"machine": machine_name,
							"fuel_type": fuel_type,
							"tank": tank_link,
						})
						meter.insert()
						created.append(("Meter", meter.name))
						meter_rows.append({"name": meter.name, "meter_code": code})

		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		raise

	return {
		"ok": True,
		"station": station.name,
		"meters": meter_rows,
		"created": {
			"islands": len(island_names),
			"machines": len(machine_names),
			"tanks": len(tank_names),
			"meters": sum(1 for c in created if c[0] == "Meter"),
		},
	}


@frappe.whitelist()
def reopen_shift(name):
	shift = frappe.get_doc("Shift", name)
	shift.reopen_shift()
	return {"ok": True, "message": "تمت إعادة فتح المناوبة"}


@frappe.whitelist()
def shift_corrections(name):
	logs = frappe.get_all(
		"Shift Correction Log",
		filters={"parent": name, "parenttype": "Shift"},
		fields=["corrected_by", "corrected_at", "field_changed", "old_value", "new_value", "reason"],
		order_by="corrected_at desc",
	)
	return {"results": logs}


@frappe.whitelist()
def setup_station():
	"""Atomic station setup for the Vue SPA wizard.
	POST /api/setup-station/ with JSON body (see _setup_station_impl).
	"""
	return _setup_station_impl(_get_body())
