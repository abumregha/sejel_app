import frappe
from frappe import _
import json


def get_list(doctype, filters=None, fields=None, limit_page_length=0, order_by=None, offset=0):
	"""Generic list getter for Vue SPA.

	Default limit 0 (unlimited): the SPA has no pagination and volumes are
	small — the old default of 20 silently truncated lists (Q47). Callers can
	still pass ?limit_page_length=N explicitly.
	"""
	if isinstance(filters, str):
		filters = json.loads(filters)
	if isinstance(fields, str):
		fields = json.loads(fields)
	if isinstance(limit_page_length, str):
		limit_page_length = int(limit_page_length)

	if not order_by:
		order_by = "modified desc"

	# Reference data (fuel types, prices, categories, companies) is global and
	# must be readable by every authenticated user — the SPA loads it for form
	# options and the dashboard reads prices server-side. get_list would apply
	# Frappe's per-role read perms and hide these from supervisors/finance.
	from .scoping import GLOBAL_DOCTYPES
	getter = frappe.get_all if doctype in GLOBAL_DOCTYPES else frappe.get_list

	result = getter(
		doctype,
		filters=filters or {},
		fields=fields or ["name", "modified"],
		limit_page_length=limit_page_length,
		order_by=order_by,
		start=offset,
	)
	total = frappe.db.count(doctype, filters=filters or {})
	return {"results": result, "total": total}


def get_doc(doctype, name):
	"""Get a single document."""
	doc = frappe.get_doc(doctype, name)
	return doc.as_dict()


def create_doc(doctype, data):
	"""Create a new document."""
	try:
		if isinstance(data, str):
			data = json.loads(data)
		doc = frappe.new_doc(doctype)
		doc.update(data)
		doc.insert()
		return doc.as_dict()
	except Exception as e:
		raise _humanize(e)


def update_doc(doctype, name, data):
	"""Update an existing document."""
	try:
		if isinstance(data, str):
			data = json.loads(data)
		doc = frappe.get_doc(doctype, name)
		if doctype == "Meter Reading":
			_clear_stale_reading_exception(doc, data)
		doc.update(data)
		doc.save()
		return doc.as_dict()
	except Exception as e:
		raise _humanize(e)


def _clear_stale_reading_exception(doc, data):
	"""A correction must be justified on its own, not by an older correction.

	`doc.update(data)` only touches the fields the client sent, so an edit that
	re-sent the two readings without an `exception_type` kept the reason from a
	PREVIOUS correction — and validate_continuity then accepted the new change
	without ever asking the operator (browser acceptance test 2026-10-09).
	"""
	if not {"start_reading", "end_reading"} & set(data or {}):
		return
	if "exception_type" in data:
		return
	if doc.get("exception_type") or doc.get("notes"):
		doc.exception_type = ""
		doc.notes = None


def delete_doc(doctype, name):
	"""Delete a document.

	Station teardown (client report 2026-10-01: "delete fails" with a bare
	LinkExistsError while the SPA dumped the user on the login page): the
	station's CONFIG children — islands, machines, meters, tanks, shift
	definitions — have no cancel permission on their DocPerms, so they are
	always draft and a hard delete is safe. We cascade them in dependency
	order, then delete the station itself. Documents with FINANCIAL history
	(shifts, readings, reconciliations, …) still have cancel permission and
	still raise LinkExistsError — that block is intentional (audit trail) and
	the SPA now explains it in Arabic via friendlyError().
	"""
	if doctype == "Station":
		# Guard BEFORE cascading: a user without station-delete permission must
		# not trigger the child cascade (that would orphan the config tree).
		if not frappe.has_permission("Station", "delete", doc=name):
			frappe.throw(_("ليست لديك صلاحية لحذف المحطات — يرجى التواصل مع مدير النظام"), frappe.PermissionError)
		_cascade_delete_station_children(name)
	try:
		frappe.delete_doc(doctype, name, ignore_missing=True)
	except frappe.PermissionError:
		frappe.throw(_("ليست لديك صلاحية لحذف هذا السجل"), frappe.PermissionError)
	return {"ok": True}


def _station_child_names(doctype, station):
	"""Names of a station's config children. Meter has NO station column
	(machine → island → station) and Tank Reading goes through its tank — a
	naive filters={"station": ...} raised UndefinedColumn (caught live)."""
	if doctype == "Meter":
		islands = _station_child_names("Island", station) or [""]
		machines = frappe.get_all("Machine", filters={"island": ["in", islands]}, pluck="name") or [""]
		return frappe.get_all("Meter", filters={"machine": ["in", machines]}, pluck="name")
	if doctype == "Tank Reading":
		tanks = _station_child_names("Tank", station) or [""]
		return frappe.get_all("Tank Reading", filters={"tank": ["in", tanks]}, pluck="name")
	return frappe.get_all(doctype, filters={"station": station}, pluck="name")


def _cascade_delete_station_children(station):
	"""Delete the station's config tree so the station itself can be removed.

	Anything still linked after this (Shift, Reconciliation, …) raises
	LinkExistsError from frappe.delete_doc — the deliberate audit block.
	"""
	for child_doctype in STATION_CONFIG_CHILDREN:
		for child in _station_child_names(child_doctype, station):
			frappe.delete_doc(child_doctype, child, ignore_missing=True)


# Station config children, dependency order (grandchildren first).
# These carry no financial history: cancel is not permitted on their DocPerms,
# so they can only exist as drafts and a hard delete loses nothing auditable.
STATION_CONFIG_CHILDREN = (
	"Meter",         # → Machine → Island (no station column)
	"Tank Reading",  # → Tank (operational log, no finance)
	"Tank",          # → Station
	"Machine",       # → Island
	"Island",        # → Station
	"Shift Definition",
)


def _humanize(e):
	"""Translate low-level DB errors into 417 ValidationErrors the SPA can
	show (client report 2026-10-01: saving a reading answered "an error
	occurred" with no explanation — huge counter values overflowed the
	numeric column and produced an unhandled 500 DataError)."""
	if isinstance(e, frappe.ValidationError) or isinstance(e, frappe.PermissionError):
		return e
	try:
		import psycopg2
		from psycopg2.errors import DataError, NumericValueOutOfRange
		if isinstance(e, (DataError, NumericValueOutOfRange)):
			frappe.throw(
				_("القيمة المُدخلة كبيرة جداً أو غير صالحة — تأكد من الأرقام المكتوبة على العداد"),
			)
	except ImportError:
		pass
	# numeric overflow arrives wrapped in a bare Exception by some drivers —
	# sniff the message too
	msg = str(e).lower()
	if "numeric field overflow" in msg or "out of range" in msg or "invalid input syntax" in msg:
		frappe.throw(
			_("القيمة المُدخلة كبيرة جداً أو غير صالحة — تأكد من الأرقام المكتوبة على العداد"),
		)
	return e
