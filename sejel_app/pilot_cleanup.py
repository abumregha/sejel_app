import frappe

# Pilot cleanup (2026-09-12): wipe ALL station/operational data so the client
# starts from a clean system. Keep: roles, fuel types (بنزين/ديزل), voucher
# categories, expense categories, marketing companies, admin + owner users.
#
# Usage (from bench):
#   bench --site sejel.local execute sejel_app.pilot_cleanup.clean --args "[]"

DELETE_ORDER = [
	# financial children first
	"Shift Fuel Summary",
	"Reconciliation",
	"POS Record",
	"Voucher",
	"Cash Collection",
	"Meter Reading",
	"Expense",
	# operations
	"Shift",
	"Shift Definition",
	"Tank Reading",
	"Fuel Reconciliation",
	"Tank Transfer",
	"Shortage Claim",
	"Delivery Request",
	"Delivery",
	# master data under stations
	"Employee",
	"Meter",
	"Machine",
	"Island",
	"Tank",
	"Station",
]


def clean(dry_run=False):
	counts = {}
	for dt in DELETE_ORDER:
		names = frappe.get_all(dt, pluck="name")
		counts[dt] = len(names)
		if not dry_run:
			for n in names:
				frappe.delete_doc(dt, n, force=True)

	# UAT test users (keep Administrator, admin@ and owner@)
	test_users = [
		u.name for u in frappe.get_all("User", fields=["name"])
		if u.name.endswith("@sejel.ly")
		and not u.name.startswith(("owner@", "admin@"))
	]
	counts["test users"] = len(test_users)
	if not dry_run:
		for u in test_users:
			frappe.delete_doc("User", u, force=True)

	# clear any leftover user-station bindings
	if not dry_run:
		frappe.db.sql("UPDATE `tabUser` SET sejel_station = NULL")
		frappe.db.commit()

	print("PILOT CLEANUP {}:".format("(DRY RUN) " if dry_run else "DONE"))
	for k, v in counts.items():
		print("  {}: {}".format(k, v))
	print("  stations left: {}".format(frappe.db.count("Station")))
	print("  shifts left: {}".format(frappe.db.count("Shift")))
	print("  reconciliations left: {}".format(frappe.db.count("Reconciliation")))
