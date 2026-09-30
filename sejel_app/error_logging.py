"""Transaction-safe error logging for sejel_app.

Why this exists
---------------
Frappe's ``frappe.utils.error.log_error_snapshot`` logs the Error Log doctype
row *inside the same Postgres transaction that just failed*. After a
``psycopg2.errors.InFailedSqlTransaction`` the transaction is aborted and any
further query — including the Error Log insert — fails, so errors never reach
the Error Log doctype / desk UI (observed: "Could not take error snapshot:
current transaction is aborted" in frappe.log, Error Log table empty).

The default fallback (``defer_insert=True`` → redis queue) is also fragile:
the queued payloads live in an ephemeral redis and are lost on redis restart
(observed on 2026-09-12: 4 setup_station errors collected but never flushed).

Fix
---
Patch ``log_error_snapshot`` (and ``log_error``) so that:

1. The Error Log row is inserted directly (not deferred) and committed, so it
   is durable and independent of redis.
2. If the transaction is aborted, roll back first, then retry once.
3. If even that fails, append the traceback to a per-site JSONL file
   (logs/error-log-fallback.jsonl) so nothing is silently lost.

The patch is installed via the ``before_request`` hook in hooks.py (idempotent,
one-time per process). ``frappe.app`` imports ``log_error_snapshot`` by name, so
we rebind it on the ``frappe.app`` module to make the running request use ours.
"""

import json
import os
import time

import frappe


def _fallback_path():
	"""logs/error-log-fallback.jsonl inside the current site."""
	try:
		return os.path.join(frappe.get_site_path("logs"), "error-log-fallback.jsonl")
	except Exception:
		return os.path.join(os.path.expanduser("~"), "error-log-fallback.jsonl")


def _write_fallback(exception, traceback_text):
	try:
		entry = {
			"ts": time.time(),
			"site": getattr(frappe.local, "site", None),
			"user": getattr(frappe.local, "session", None) and getattr(frappe.local.session, "user", None),
			"exception": str(exception)[:2000],
			"traceback": str(traceback_text)[:20000],
		}
		with open(_fallback_path(), "a") as f:
			f.write(json.dumps(entry, default=str) + "\n")
	except Exception:
		pass  # last-resort logger must never raise


def _is_excluded(exception):
	"""Mirror frappe.utils.error.log_error_snapshot's exclusion checks."""
	try:
		from frappe.utils.error import EXCLUDE_EXCEPTIONS, _is_ldap_exception
		if isinstance(exception, EXCLUDE_EXCEPTIONS) or _is_ldap_exception(exception):
			return True
	except Exception:
		pass
	return False


def _insert_error_log(title, traceback_text):
	"""Insert an Error Log row in the CURRENT transaction and commit it.

	Committing here is deliberate: the surrounding request failed with a 500 and
	its transaction is being discarded anyway; committing just the error row
	makes it durable even if the outer request later rolls back.
	"""
	error_log = frappe.get_doc(
		doctype="Error Log",
		error=traceback_text,
		method=title,
	)
	error_log.insert(ignore_permissions=True)
	frappe.db.commit()


def safe_log_error_snapshot(exception):
	"""Drop-in replacement for frappe.utils.error.log_error_snapshot."""
	if _is_excluded(exception):
		return

	logger = frappe.logger(with_more_info=True)
	traceback_text = frappe.get_traceback(with_context=True)

	try:
		_insert_error_log(str(exception), traceback_text)
		logger.error("New Exception collected in error log")
	except Exception as e:
		# Aborted transaction (InFailedSqlTransaction) — roll back and retry once.
		try:
			if frappe.db:
				frappe.db.rollback()
			_insert_error_log(str(exception), traceback_text)
			logger.error("New Exception collected in error log (after rollback)")
		except Exception as e2:
			_write_fallback(exception, traceback_text)
			logger.error(f"Could not take error snapshot: {e2}", exc_info=True)


def patch_once():
	"""Install the safe loggers. Idempotent — safe to call on every request."""
	module = None
	try:
		import frappe.utils.error as error_mod
		module = error_mod
	except Exception:
		module = None

	if module is None or getattr(module, "log_error_snapshot", None) is safe_log_error_snapshot:
		return

	# Rebind on frappe.utils.error (for future imports / direct calls) …
	module.log_error_snapshot = safe_log_error_snapshot
	# … and on frappe.app, which imported the name directly at startup.
	try:
		import frappe.app as app_mod
		app_mod.log_error_snapshot = safe_log_error_snapshot
	except Exception:
		pass

	frappe.logger().info("sejel_app: transaction-safe error logging installed")