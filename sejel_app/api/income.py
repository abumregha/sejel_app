import uuid

import frappe
from frappe import _
from frappe.utils import now_datetime


@frappe.whitelist()
def record_income_legs(
	shift,
	cash_amount=0,
	coupon_legs=None,
	epayment_amount=0,
	epayment_count=0,
	request_id=None,
):
	"""Record one income entry (cash + coupons + e-payment) for a shift.

	The SPA used to POST each leg separately and, when one failed, told the
	operator to press save again — which re-posted the legs that had already
	succeeded and duplicated real money rows (browser acceptance test
	2026-10-09: two identical Voucher rows, an inflated total_vouchers on that
	day's reconciliation).

	Two changes make a retry safe:

	* every leg is created in ONE request, so a failure is reported per leg
	  instead of leaving the operator guessing what was saved;
	* each leg carries `income_request`, and a leg already stored under the same
	  request id is skipped. The SPA keeps one id per entry form, so pressing
	  save twice completes only what is missing.
	"""
	if not request_id:
		request_id = f"income-{uuid.uuid4().hex[:12]}"

	posted = []
	failed = []

	def already(kind, filters):
		return bool(frappe.db.exists(kind, {**filters, "income_request": request_id}))

	amount = _num(cash_amount)
	if amount > 0:
		if already("Cash Collection", {"shift": shift}):
			posted.append({"leg": "cash", "ok": True, "skipped": True})
		else:
			posted.append(
				_post(
					"Cash Collection",
					{
						"shift": shift,
						"amount": amount,
						"time": now_datetime(),  # Datetime field, not a bare clock time
						"income_request": request_id,
					},
					"cash",
					failed,
				)
			)

	for leg in coupon_legs or []:
		category = leg.get("category")
		count = _num(leg.get("count"))
		if not category or count <= 0:
			continue
		value = _num(leg.get("value")) or frappe.db.get_value(
			"Voucher Category", category, "value"
		)
		filters = {"shift": shift, "category": category}
		if already("Voucher", filters):
			posted.append({"leg": f"coupon_{category}", "ok": True, "skipped": True})
			continue
		posted.append(
			_post(
				"Voucher",
				{
					"shift": shift,
					"category": category,
					"count": count,
					"total_value": count * (value or 0),
					"income_request": request_id,
				},
				f"coupon_{category}",
				failed,
			)
		)

	amount = _num(epayment_amount)
	if amount > 0:
		if already("POS Record", {"shift": shift}):
			posted.append({"leg": "epayment", "ok": True, "skipped": True})
		else:
			posted.append(
				_post(
					"POS Record",
					{
						"shift": shift,
						"total_amount": amount,
						"transaction_count": max(1, int(_num(epayment_count) or 1)),
						"income_request": request_id,
					},
					"epayment",
					failed,
				)
			)

	return {
		"request_id": request_id,
		"legs": posted,
		"failed": failed,
		"ok": not failed,
	}


def _post(doctype, values, leg, failed):
	try:
		frappe.get_doc({"doctype": doctype, **values}).insert()
		return {"leg": leg, "ok": True}
	except Exception as exc:  # noqa: BLE001 — one bad leg must not lose the others
		frappe.log_error(
			title=f"income leg failed: {leg}",
			message=frappe.get_traceback(),
			reference_doctype=doctype,
		)
		failed.append({"leg": leg, "error": _friendly(exc)})
		return {"leg": leg, "ok": False}


def _num(value):
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _friendly(exc):
	"""The doctype's own Arabic validation message, never a stack trace."""
	message = str(exc)
	for candidate in (exc, getattr(exc, "_exc_source", None)):
		if candidate is None:
			continue
	return message if isinstance(message, str) else _(
		"تعذّر حفظ أحد البنود"
	)
