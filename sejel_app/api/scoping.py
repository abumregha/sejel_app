import frappe


def scoped_station():
	"""The station name this user is bound to, or None.

	Opt-in scoping (client request: "users — not owner or admin — should only
	view a certain station"). Admins (System Manager) and owners/managers
	(Sejel Manager) are never scoped. Everyone else is scoped only when a
	`sejel_station` is set on their User record — users without a binding keep
	today's behavior (all stations), so nobody gets locked out by default.
	"""
	user = frappe.session.user
	if user in ("Administrator", "Guest"):
		return None
	if "System Manager" in frappe.get_roles(user):
		return None
	if "Sejel Manager" in frappe.get_roles(user):
		return None
	return frappe.db.get_value("User", user, "sejel_station") or None


# Doctypes that carry their own `station` link — the filter can be injected
# directly. Everything else resolves through a parent (shift/tank/machine/…).
DIRECT_STATION_DOCTYPES = {
	"Station", "Island", "Machine", "Tank", "Employee", "Shift Definition",
	"Shift", "Expense", "Expense Category", "Voucher Settlement",
	"Reconciliation", "Delivery", "Delivery Request", "Tank Transfer",
	"Fuel Reconciliation",
}


def _names(doctype, field, value):
	rows = frappe.get_all(doctype, filters={field: value}, pluck="name")
	return rows or [""]  # [""] matches nothing but keeps SQL valid


def apply_to_filters(doctype, filters):
	"""Force the station filter onto a filters dict for station-bound users.

	Doctypes with a station link get `station` injected directly (a user-supplied
	station param cannot override scoping). Child doctypes are filtered through
	their parent's ids. Doctypes with no path to a station are left untouched.
	"""
	station = scoped_station()
	if not station:
		return filters
	filters = dict(filters or {})

	if doctype == "Station":
		# the station IS the document — scope on its name
		filters["name"] = station
	elif doctype in DIRECT_STATION_DOCTYPES:
		filters["station"] = station
	elif doctype in ("Meter Reading", "Cash Collection", "Voucher", "POS Record"):
		filters["shift"] = ["in", _names("Shift", "station", station)]
	elif doctype == "Shift Fuel Summary":
		filters["reconciliation"] = ["in", _names("Reconciliation", "station", station)]
	elif doctype == "Tank Reading":
		filters["tank"] = ["in", _names("Tank", "station", station)]
	elif doctype == "Meter":
		filters["machine"] = ["in", _names("Machine", "station", station)]
	elif doctype == "Shortage Claim":
		filters["delivery"] = ["in", _names("Delivery", "station", station)]
	return filters


STATION_CHILD_RESOURCES = {
	# resources whose station is reached through a parent link
	"cash-collections": ("shift", "Shift", "station"),
	"vouchers": ("shift", "Shift", "station"),
	"pos-records": ("shift", "POS Record", None),  # POS Record has no station field
	"meter-readings": ("meter", "Meter", None),    # Meter has no station field
}


# Reference data with no station link — readable by everyone.
GLOBAL_DOCTYPES = {"Fuel Type", "Fuel Price", "Marketing Company", "Voucher Category"}


def _resolve_doc_station(doctype, name):
	"""Find the station a document belongs to, following its parent chain."""
	if doctype == "Meter":
		# Meter has no station: meter → machine → island → station
		machine = frappe.db.get_value("Meter", name, "machine")
		island = frappe.db.get_value("Machine", machine, "island") if machine else None
		return frappe.db.get_value("Island", island, "station") if island else None
	if doctype == "Tank Reading":
		tank = frappe.db.get_value("Tank Reading", name, "tank")
		return frappe.db.get_value("Tank", tank, "station") if tank else None
	if doctype == "Shortage Claim":
		delivery = frappe.db.get_value("Shortage Claim", name, "delivery")
		return frappe.db.get_value("Delivery", delivery, "station") if delivery else None
	doc_station = frappe.db.get_value(doctype, name, "station")
	if doc_station is None:
		# child-of-shift docs (cash collections, vouchers, POS, readings):
		# resolve through the parent shift's station
		parent = frappe.db.get_value(doctype, name, "shift")
		if parent:
			doc_station = frappe.db.get_value("Shift", parent, "station")
	if doc_station is None and doctype == "Shift Fuel Summary":
		recon = frappe.db.get_value("Shift Fuel Summary", name, "reconciliation")
		if recon:
			doc_station = frappe.db.get_value("Reconciliation", recon, "station")
	return doc_station


def check_station(doctype, name):
	"""Raise if a station-bound user reads/writes a doc outside their station."""
	station = scoped_station()
	if not station:
		return
	if doctype in GLOBAL_DOCTYPES:
		return
	if doctype == "Station":
		if name != station:
			frappe.throw("غير مصرح لك بالوصول إلا لمحطتك", frappe.PermissionError)
		return
	doc_station = _resolve_doc_station(doctype, name)
	if doc_station != station:
		frappe.throw("غير مصرح لك بالوصول إلا لبيانات محطتك", frappe.PermissionError)
