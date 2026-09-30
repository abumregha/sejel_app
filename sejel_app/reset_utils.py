import frappe


def inspect_counts():
    tables = [
        "Station", "Island", "Machine", "Meter", "Tank", "Employee",
        "Shift Definition", "Shift", "Meter Reading", "Cash Collection",
        "Voucher", "POS Record", "Expense", "Voucher Settlement",
        "Reconciliation", "Shift Fuel Summary", "Delivery", "Delivery Request",
        "Tank Reading", "Tank Transfer", "Fuel Reconciliation", "Shortage Claim",
        "Fuel Price", "Fuel Type", "Expense Category", "Voucher Category",
        "Marketing Company",
    ]
    out = {}
    for t in tables:
        out[t] = frappe.db.count(t)
    return out


# Tables to wipe completely (transactions first, then master data).
WIPE = [
    # transactions
    "Shift Fuel Summary",
    "Reconciliation",
    "Meter Reading",
    "Cash Collection",
    "Voucher",
    "POS Record",
    "Expense",
    "Voucher Settlement",
    "Tank Reading",
    "Tank Transfer",
    "Fuel Reconciliation",
    "Shortage Claim",
    "Delivery",
    "Delivery Request",
    "Shift",
    # master data (hierarchy: children first)
    "Meter",
    "Machine",
    "Island",
    "Tank",
    "Employee",
    "Shift Definition",
    "Fuel Price",
    "Station",
]


def wipe_all(keep_categories=True):
    """Delete all seeded/test data. Keeps: Users, Fuel Types,
    Expense Categories, Voucher Categories, Marketing Companies."""
    deleted = {}
    for t in WIPE:
        names = frappe.get_all(t, pluck="name")
        for n in names:
            try:
                frappe.delete_doc(t, n, force=True, ignore_permissions=True)
            except Exception as e:
                # last resort for linked leftovers
                frappe.db.delete(t, n)
        deleted[t] = len(names)
    frappe.db.commit()
    return deleted


def set_fuel_prices(price=0.15):
    """Set selling_price=price for every fuel type, effective today,
    deactivating any previous price rows."""
    import datetime
    today = datetime.date.today().isoformat()

    # deactivate old prices
    for name in frappe.get_all("Fuel Price", pluck="name"):
        frappe.db.set_value("Fuel Price", name, "is_active", 0)

    created = []
    for ft in frappe.get_all("Fuel Type", pluck="name"):
        fp = frappe.get_doc({
            "doctype": "Fuel Price",
            "fuel_type": ft,
            "selling_price": price,
            "cost_per_liter": 0,
            "effective_date": today,
            "is_active": 1,
        })
        fp.insert(ignore_permissions=True)
        created.append(f"{ft}: {price}")
    frappe.db.commit()
    return created
