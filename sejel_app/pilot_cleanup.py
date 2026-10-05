import frappe

# Pilot cleanup: wipe operational/financial rows so the client starts from a
# clean system while the stations themselves stay usable.
#
# Default (keep_stations=True): deletes readings, shifts, reconciliations,
# deliveries, vouchers, POS records, collections and the rest of the
# transactional data. Keeps Station + everything under it (Island, Meter,
# Machine, Tank, Employee), keeps every User, keeps Fuel Price.
#
# keep_stations=False restores the original behaviour (wipe masters too), and
# wipe_users=True also removes the *@sejel.ly test accounts (admin/owner kept).
#
# Usage (from bench):
#   dry run: bench --site sejel.local execute sejel_app.pilot_cleanup.clean --args "[true]"
#   real:    bench --site sejel.local execute sejel_app.pilot_cleanup.clean --args "[false]"

OPERATIONAL_DOCS = [
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
]

STATION_MASTERS = [
	"Employee",
	"Meter",
	"Machine",
	"Island",
	"Tank",
	"Station",
]


def clean(dry_run=False, keep_stations=True, wipe_users=False, zero_state=True):
	counts = {}
	for dt in OPERATIONAL_DOCS + ([] if keep_stations else STATION_MASTERS):
		names = frappe.get_all(dt, pluck="name")
		counts[dt] = len(names)
		if not dry_run:
			for n in names:
				frappe.delete_doc(dt, n, force=True)

	if wipe_users:
		test_users = [
			u.name for u in frappe.get_all("User", fields=["name"])
			if u.name.endswith("@sejel.ly")
			and not u.name.startswith(("owner@", "admin@"))
		]
		counts["test users"] = len(test_users)
		if not dry_run:
			for u in test_users:
				frappe.delete_doc("User", u, force=True)
			frappe.db.sql("UPDATE `tabUser` SET sejel_station = NULL")

	if zero_state:
		counts["tank levels reset"] = frappe.db.count("Tank")
		counts["meter counters reset"] = frappe.db.count("Meter")
		if not dry_run:
			frappe.db.sql("UPDATE `tabTank` SET current_level = 0")
			frappe.db.sql("UPDATE `tabMeter` SET current_reading = 0")

	if not dry_run:
		frappe.db.commit()

	print("PILOT CLEANUP {}:".format("(DRY RUN) " if dry_run else "DONE"))
	for k, v in counts.items():
		print("  {}: {}".format(k, v))
	print("  stations left: {}".format(frappe.db.count("Station")))
	print("  users left: {}".format(frappe.db.count("User")))
	print("  shifts left: {}".format(frappe.db.count("Shift")))
	print("  readings left: {}".format(frappe.db.count("Meter Reading")))
	print("  reconciliations left: {}".format(frappe.db.count("Reconciliation")))
