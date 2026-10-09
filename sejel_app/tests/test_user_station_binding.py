import frappe
from frappe.tests.utils import FrappeTestCase


class TestUserStationBinding(FrappeTestCase):
	"""`User.sejel_station` must exist on EVERY site, including a fresh install.

	Found during the browser acceptance test (2026-10-09): on a site created with
	`bench new-site --install-app sejel_app` the shipped patch
	`v1_user_station_binding` was recorded as executed but left no Custom Field
	and no column, so `api/scoping.scoped_station()` raised UndefinedColumn and
	every station-scoped request 500'd for supervisors. The install/migrate hooks
	are what actually guarantee the field.
	"""

	def _field_doc_exists(self):
		return bool(
			frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "sejel_station"})
		)

	def _column_exists(self):
		return "sejel_station" in [
			r[0]
			for r in frappe.db.sql(
				"""
				select column_name from information_schema.columns
				where table_name = %s
				""",
				("tabUser",),
			)
		]

	def _drop_field(self):
		"""Simulate the broken fresh install: the patch ran, nothing survived."""
		for row in frappe.get_all(
			"Custom Field", filters={"dt": "User", "fieldname": "sejel_station"}, pluck="name"
		):
			frappe.delete_doc("Custom Field", row, ignore_permissions=True, force=True)
		# Postgres DDL is transactional, so the test runner's rollback undoes
		# this — a commit here would persist the test's own fixtures.
		frappe.db.sql("ALTER TABLE `tabUser` DROP COLUMN IF EXISTS sejel_station")
		self.assertFalse(self._field_doc_exists())
		self.assertFalse(self._column_exists())

	def test_ensure_creates_missing_field_and_column(self):
		from sejel_app.install import ensure_user_station_binding

		self._drop_field()
		ensure_user_station_binding()
		self.assertTrue(self._field_doc_exists())
		self.assertTrue(self._column_exists())

	def test_ensure_is_idempotent(self):
		from sejel_app.install import ensure_user_station_binding

		ensure_user_station_binding()
		ensure_user_station_binding()
		count = frappe.db.count("Custom Field", {"dt": "User", "fieldname": "sejel_station"})
		self.assertEqual(count, 1)

	def test_hooks_are_wired(self):
		hooks = frappe.get_hooks()
		self.assertIn("sejel_app.install.after_install", hooks.get("after_install", []))
		self.assertIn("sejel_app.install.after_migrate", hooks.get("after_migrate", []))
