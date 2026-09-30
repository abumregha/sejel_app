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
	if isinstance(data, str):
		data = json.loads(data)
	doc = frappe.new_doc(doctype)
	doc.update(data)
	doc.insert()
	return doc.as_dict()


def update_doc(doctype, name, data):
	"""Update an existing document."""
	if isinstance(data, str):
		data = json.loads(data)
	doc = frappe.get_doc(doctype, name)
	doc.update(data)
	doc.save()
	return doc.as_dict()


def delete_doc(doctype, name):
	"""Delete a document."""
	frappe.delete_doc(doctype, name)
	return {"ok": True}
