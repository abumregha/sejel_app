import frappe


def execute():
	"""User→Station binding for supervisor scoping (docs/DASHBOARD_REDESIGN_PROMPT.md §3.1).

	Kept for sites whose patch log predates the install hooks; the field
	definition itself now lives in sejel_app/install.py, which after_install and
	after_migrate call on every site (a fresh install once recorded this patch as
	done while the Custom Field never survived the install transaction).
	"""
	from sejel_app.install import ensure_user_station_binding

	ensure_user_station_binding()
