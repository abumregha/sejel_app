import frappe


def execute():
	"""Client reality: only two fuel types exist — ديزل and بنزين.

	The seed data (inherited from the legacy Django database) created
	بنزين 91 and بنزين 95. There is no 91/95 in this market, so merge them
	into بنزين: every Tank/Meter/Fuel Price/Shift Fuel Summary/Delivery/
	Delivery Request/Tank Transfer/Fuel Reconciliation row pointing at a
	variant is repointed at بنزين, then the variants are deleted.
	"""
	target = "بنزين"
	variants = ["بنزين 91", "بنزين 95"]

	# The canonical بنزين record must exist before anything can point at it.
	if not frappe.db.exists("Fuel Type", target):
		doc = frappe.new_doc("Fuel Type")
		doc.update({"fuel_name": target, "fuel_name_en": "Benzine", "is_active": 1})
		doc.insert()
		frappe.db.commit()

	for variant in variants:
		if not frappe.db.exists("Fuel Type", variant):
			continue

		linked_doctypes = frappe.get_all(
			"DocField",
			filters={"parent": ("in", [
				"Tank", "Meter", "Fuel Price", "Shift Fuel Summary",
				"Delivery", "Delivery Request", "Tank Transfer",
				"Fuel Reconciliation",
			]), "fieldtype": "Link", "options": "Fuel Type"},
			pluck="parent",
		)
		for dt in set(linked_doctypes):
			frappe.db.sql(
				"UPDATE `tab{}` SET fuel_type = %s WHERE fuel_type = %s".format(dt),
				(target, variant),
			)

		frappe.db.sql("DELETE FROM `tabFuel Type` WHERE name = %s", variant)
		frappe.db.commit()
		print("merged fuel type {} -> {}".format(variant, target))
