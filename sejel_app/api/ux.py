"""Client-experience capture endpoints (SPA telemetry + feedback).

Endpoints
---------
POST /api/method/sejel_app.api.ux.report_client_error
    Frontend errors (window.onerror / unhandledrejection), failed API calls
    (4xx/5xx + latency), slow API calls and page visits. Throttled and
    truncated; guests allowed (login-page errors) with a tighter limit.

POST /api/method/sejel_app.api.ux.submit_feedback
    The in-app "was this hard?" widget — rating + optional comment + page.

GET /api/method/sejel_app.api.ux.ux_summary  (System Manager only)
    Aggregated 7-day counts for a quick admin glance (desk report uses the
    Client Error / Client Feedback lists directly).

Design notes
------------
- Writes go through frappe.get_doc(...).insert() with ignore_permissions so
  the SPA's session user does not need Client Error read/write on the desk.
- Rate limiting is done in-process (site-agnostic, no extra redis keys):
  per user+kind+minute buckets. Good enough for a pilot; revisit if the
  client count grows.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

MAX_LEN_MESSAGE = 1000
MAX_LEN_STACK = 5000
MAX_LEN_PAGE = 300
MAX_LEN_SOURCE = 300
MAX_LEN_COMMENT = 3000

GUEST_HOURLY = 20
USER_HOURLY = 120

_KINDS = {"error", "api_fail", "slow", "visit"}


def _user_agent():
	"""Request User-Agent, or '' outside a request (console/worker safe)."""
	try:
		return (frappe.get_request_header("User-Agent") or "")[:500]
	except Exception:
		return ""


def _throttle(key, limit):
	"""In-process sliding-window-ish counter; returns True when over limit."""
	bucket = f"ux-throttle::{key}::{int(frappe.utils.now_datetime().timestamp() // 3600)}"
	count = cint(frappe.cache.get_value(bucket)) + 1
	frappe.cache.set_value(bucket, count, expires_in_sec=3700)
	return count > limit


@frappe.whitelist(allow_guest=True)
def report_client_error(kind="error", message=None, source=None, page=None, stack=None, request_path=None):
	"""Record a client-side error / api failure / slow call / page visit."""
	kind = kind if kind in _KINDS else "error"

	user = frappe.session.user
	is_guest = user == "Guest"

	limit = GUEST_HOURLY if is_guest else USER_HOURLY
	if _throttle(f"{user}:{kind}", limit):
		return {"ok": True, "skipped": "throttled"}

	# Guests only get here from the login page — keep it that way.
	if is_guest and page and "/login" not in page:
		return {"ok": True, "skipped": "guest-not-allowed"}

	doc = frappe.get_doc(
		doctype="Client Error",
		kind=kind,
		message=(message or "")[:MAX_LEN_MESSAGE],
		source=(source or "")[:MAX_LEN_SOURCE],
		page=(page or "")[:MAX_LEN_PAGE],
		stack=(stack or "")[:MAX_LEN_STACK],
		request_path=(request_path or "")[:MAX_LEN_PAGE],
		user_agent=_user_agent(),
		session_user=None if is_guest else user,
		occurred_at=now_datetime(),
	)
	doc.insert(ignore_permissions=True)
	return {"ok": True}


@frappe.whitelist()
def submit_feedback(rating="ok", category=None, comment=None, page=None):
	"""Record in-app feedback from the UX widget."""
	rating = rating if rating in ("hard", "ok", "easy") else "ok"

	if _throttle(f"{frappe.session.user}:feedback", GUEST_HOURLY):
		return {"ok": True, "skipped": "throttled"}

	doc = frappe.get_doc(
		doctype="Client Feedback",
		rating=rating,
		category=(category or "")[:200],
		comment=(comment or "")[:MAX_LEN_COMMENT],
		page=(page or "")[:MAX_LEN_PAGE],
		user_agent=_user_agent(),
		session_user=None if frappe.session.user == "Guest" else frappe.session.user,
	)
	doc.insert(ignore_permissions=True)
	return {"ok": True}


@frappe.whitelist()
def ux_summary():
	"""Aggregated client-experience stats for the last 7 days (admins only)."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	since = frappe.utils.add_days(now_datetime(), -7)

	errors = frappe.get_all(
		"Client Error",
		filters={"creation": [">=", since], "kind": ["in", ["error", "api_fail"]]},
		fields=["kind", "message", "page", "request_path", "occurred_at"],
		order_by="creation desc",
		limit_page_length=500,
	)

	# Group by message prefix (first 80 chars) — good enough to spot clusters
	grouped = {}
	for e in errors:
		key = (e.kind, (e.message or "")[:80])
		g = grouped.setdefault(key, {"kind": e.kind, "sample": e.message, "page": e.page, "count": 0, "last": e.occurred_at})
		g["count"] += 1

	feedback = frappe.get_all(
		"Client Feedback",
		filters={"creation": [">=", since]},
		fields=["rating", "count(name) as count"],
		group_by="rating",
	)

	visits = frappe.db.count("Client Error", {"kind": "visit", "creation": [">=", since]})
	slow = frappe.db.count("Client Error", {"kind": "slow", "creation": [">=", since]})

	return {
		"error_groups": sorted(grouped.values(), key=lambda g: g["count"], reverse=True)[:10],
		"feedback": {r.rating: r.count for r in feedback},
		"visits_7d": visits,
		"slow_calls_7d": slow,
	}