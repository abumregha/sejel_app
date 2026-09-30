import frappe
from frappe import _
from frappe.utils import nowdate, getdate

from .scoping import scoped_station

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _day_key(d):
	"""Frappe Shift Definition `days` convention: sat, sun, mon…"""
	return DAY_KEYS[d.weekday()]


def generate_shifts_for_date(date=None, emergency=0):
	"""Create today's (or a given date's) Shift records from Shift Definitions.

	Phase-2 decision: shift generation is automatic from the definitions —
	plus an **emergency 24h mode** that creates all active definitions for the
	station regardless of the weekday filter (crisis / manual override day).

	- Skips (station, definition, date) combos that already exist — re-running
	  is safe and never duplicates.
	- Scoped users can only generate for their own station.
	- Creates shifts in `scheduled` status; activation stays a manual step.
	"""
	date = getdate(date) if date else getdate(nowdate())
	emergency = bool(int(emergency or 0))

	station = scoped_station() or frappe.form_dict.get("station") or None
	if not station:
		stations = frappe.get_all("Station", filters={"status": "active"}, pluck="name")
	else:
		stations = [station]
		if not frappe.db.exists("Station", station):
			frappe.throw(_("المحطة غير موجودة"), frappe.DoesNotExistError)

	dkey = _day_key(date)
	created, skipped = 0, 0
	for st in stations:
		definitions = frappe.get_all(
			"Shift Definition",
			filters={"station": st, "is_active": 1},
			fields=["name", "definition_name", "island", "start_time", "end_time", "days"],
		)
		for d in definitions:
			days = (d.days or "").lower()
			if not emergency and days and dkey not in days:
				skipped += 1
				continue
			if frappe.db.exists("Shift", {"station": st, "definition": d.name, "date": date}):
				skipped += 1
				continue
			doc = frappe.new_doc("Shift")
			doc.update({
				"shift_name": "{} — {}".format(d.definition_name or d.name, date),
				"station": st,
				"definition": d.name,
				"island": d.island or None,
				"employee": d.default_employee or None,
				"date": date,
				"start_time": d.start_time,
				"end_time": d.end_time,
				"status": "scheduled",
			})
			doc.insert()
			created += 1

	mode = "طارئة (كل التعريفات)" if emergency else "عادية (حسب الأيام)"
	return {
		"ok": True,
		"date": str(date),
		"mode": mode,
		"created": created,
		"skipped": skipped,
	}
