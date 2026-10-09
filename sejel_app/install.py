import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

# The one field every station-scoped code path depends on:
# api/scoping.scoped_station(), api/dashboard.py, api/views.py, api/auth.py.
# It has to exist on EVERY site — see the test module for what happens when it
# does not.
USER_STATION_FIELD = {
	"fieldname": "sejel_station",
	"fieldtype": "Link",
	"options": "Station",
	"label": "Sejel Station",
	"insert_after": "mobile_no",
	"description": "المحطة المرتبطة بهذا المستخدم (المشرف/العامل). يُترك فارغاً للمالك والإدارة.",
}


def ensure_user_station_binding():
	"""Create `User.sejel_station` when it is missing. Safe to call any time.

	The patch `v1_user_station_binding` is recorded as executed during
	`bench new-site --install-app`, but the Custom Field it inserted did not
	survive the install transaction on a fresh site — the patch log said "done"
	while the column was absent, and nothing ever re-ran it. Every
	station-scoped request then failed with UndefinedColumn for supervisors.

	Install and migrate hooks are the durable guarantee: they run on new sites
	and on every migration, and this function is a no-op once the field exists.
	"""
	if frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "sejel_station"}):
		return

	create_custom_field("User", dict(USER_STATION_FIELD), ignore_validate=True)
	frappe.db.commit()


def after_install():
	ensure_user_station_binding()


def after_migrate():
	ensure_user_station_binding()
