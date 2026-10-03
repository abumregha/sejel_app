import frappe
from frappe import _
import json


@frappe.whitelist(allow_guest=True)
def login():
	"""Authenticate user and return user info for Vue SPA."""
	data = frappe.form_dict or {}
	if not data or not data.get("username"):
		try:
			data = json.loads(frappe.request.data or "{}")
		except Exception:
			data = {}

	username = data.get("username")
	password = data.get("password")

	if not username or not password:
		frappe.throw(_("Username and password required"))

	user_email = frappe.db.get_value("User", {"username": username}, "name")
	if not user_email:
		user_email = frappe.db.get_value("User", {"email": username}, "name")
	if not user_email:
		user_email = username

	login_manager = frappe.auth.LoginManager()
	login_manager.user = user_email
	login_manager.authenticate(user=user_email, pwd=password)
	login_manager.login_as(user=user_email)

	return {
		"user": _build_user_response(),
		# Lazily creates and persists the token so the SPA can send it back
		# via the X-Frappe-CSRF-Token header (validated in frappe/auth.py).
		"csrf_token": frappe.sessions.get_csrf_token(),
	}


@frappe.whitelist(allow_guest=True)
def logout():
	"""Destroy the server session.

	The SPA logout used to be client-side only: it cleared the Pinia store and
	redirected, but the `sid` cookie stayed valid, so pressing Back — or reopening
	a tab that had the app cached — restored a live authenticated session without
	any credential (QA-1). This ends the session server-side and clears the cookie.
	"""
	login_manager = frappe.auth.LoginManager()
	login_manager.logout()
	return {"ok": True}


@frappe.whitelist(allow_guest=True)
def get_me():
	"""Return current user info. Returns 401 if not authenticated."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not authenticated"), frappe.AuthenticationError)

	return _build_user_response()


@frappe.whitelist(allow_guest=True)
def admin_set_user_password():
	"""Admin-only: reset a user's password or disable/enable their account.

	POST /api/auth/set-user-password/ {username, new_password?, enabled?}
	Phase-2 decision (Q-passwords): admins hand a fresh password to the
	employee; there is no email flow in this environment.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not authenticated"), frappe.AuthenticationError)
	if "System Manager" not in frappe.get_roles(frappe.session.user):
		frappe.throw(_("هذه العملية متاحة لمدير النظام فقط"), frappe.PermissionError)

	data = {}
	try:
		data = json.loads(frappe.request.data or "{}")
	except Exception:
		pass

	username = (data.get("username") or "").strip()
	new_password = data.get("new_password") or ""
	enabled = data.get("enabled")
	if not username:
		frappe.throw(_("اسم المستخدم مطلوب"))

	user_name = frappe.db.get_value("User", {"username": username}, "name") \
		or frappe.db.get_value("User", {"email": username}, "name") \
		or (username if frappe.db.exists("User", username) else None)
	if not user_name:
		frappe.throw(_("المستخدم غير موجود"), frappe.DoesNotExistError)
	if user_name in ("Administrator", "Guest"):
		frappe.throw(_("لا يمكن تعديل هذا الحساب"), frappe.PermissionError)

	out = {"user": user_name}
	if new_password:
		from frappe.utils.password import update_password
		if len(new_password) < 6:
			frappe.throw(_("كلمة المرور يجب أن تكون 6 أحرف على الأقل"))
		update_password(user_name, new_password)
		out["password_updated"] = True
	if enabled is not None:
		frappe.db.set_value("User", user_name, "enabled", 1 if enabled else 0)
		out["enabled"] = bool(enabled)
	frappe.db.commit()
	return out


def _build_user_response():
	user_doc = frappe.get_doc("User", frappe.session.user)

	role = "supervisor"
	for r in user_doc.roles:
		if "Sejel Manager" in r.role:
			role = "manager"
			break
		elif "Sejel Finance" in r.role:
			role = "finance"
			break
		elif "Sejel Supervisor" in r.role:
			role = "supervisor"
			break
		elif r.role == "System Manager":
			role = "admin"
			break

	# Supervisor binding: supervisors are scoped to their linked Station; owners,
	# admins and finance are unbound (they may use the station selector).
	station_id = getattr(user_doc, "sejel_station", None) or None
	if role not in ("supervisor",):
		station_id = None

	return {
		"id": user_doc.name,
		"username": user_doc.username or user_doc.name,
		"email": user_doc.email,
		"full_name": user_doc.full_name,
		"role": role,
		"is_staff": role == "admin",
		"station_id": station_id,
		# CSRF token for unsafe methods (POST/PUT/DELETE) from the SPA —
		# sent back via the X-Frappe-CSRF-Token header (see frontend api.js).
		"csrf_token": frappe.sessions.get_csrf_token(),
	}
