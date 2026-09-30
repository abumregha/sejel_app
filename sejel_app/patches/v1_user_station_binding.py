import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
	"""User→Station binding for supervisor scoping (docs/DASHBOARD_REDESIGN_PROMPT.md §3.1).

	Idempotent: create_custom_field no-ops when the field already exists.
	"""
	create_custom_field(
		"User",
		{
			"fieldname": "sejel_station",
			"fieldtype": "Link",
			"options": "Station",
			"label": "Sejel Station",
			"insert_after": "mobile_no",
			"description": "المحطة المرتبطة بهذا المستخدم (المشرف/العامل). يُترك فارغاً للمالك والإدارة.",
		},
		ignore_validate=True,
	)
	frappe.db.commit()
