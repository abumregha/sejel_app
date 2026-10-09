app_name = "sejel_app"
app_title = "Sejel App"
app_publisher = "sejel"
app_description = "Fuel Station Management System"
app_email = "admin@sejel.ly"
app_license = "mit"

# Fix CORS for Vue SPA
# CORS: the Vue SPA is served same-origin via nginx (port 8004), so browser
# requests never need cross-origin access. Pin to the server's own origin —
# wildcard CORS on a financial system is an open-door policy.
allow_cors = ["http://102.213.180.186:8004"]

# Website route rules - serve Vue SPA
website_route_rules = [
	{
		"from_route": "/app/<path:app_path>",
		"to_route": "app",
	},
	{
		"from_route": "/app",
		"to_route": "app",
	},
]

# Override whitelisted methods for API
override_whitelisted_methods = {
	"sejel_app.api.auth.login": "sejel_app.api.auth.login",
}

# Transaction-safe error logging: Frappe's log_error_snapshot dies inside an
# aborted Postgres transaction (InFailedSqlTransaction) and the deferred-insert
# fallback is lost on redis restart — errors never reach the Error Log doctype.
# This hook installs a patched logger once per process (idempotent).
before_request = ["sejel_app.error_logging.patch_once"]

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "sejel_app",
# 		"logo": "/assets/sejel_app/logo.png",
# 		"title": "Sejel App",
# 		"route": "/sejel_app",
# 		"has_permission": "sejel_app.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/sejel_app/css/sejel_app.css"
# app_include_js = "/assets/sejel_app/js/sejel_app.js"

# include js, css files in header of web template
# web_include_css = "/assets/sejel_app/css/sejel_app.css"
# web_include_js = "/assets/sejel_app/js/sejel_app.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "sejel_app/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "sejel_app/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "sejel_app.utils.jinja_methods",
# 	"filters": "sejel_app.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "sejel_app.install.before_install"
# after_install — and after_migrate — guarantee `User.sejel_station` exists.
# Without it a fresh `bench new-site --install-app sejel_app` leaves the column
# missing (the patch log claims it ran) and every station-scoped request 500s
# for supervisors. See sejel_app/tests/test_user_station_binding.py.
after_install = "sejel_app.install.after_install"
after_migrate = "sejel_app.install.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "sejel_app.uninstall.before_uninstall"
# after_uninstall = "sejel_app.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "sejel_app.utils.before_app_install"
# after_app_install = "sejel_app.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "sejel_app.utils.before_app_uninstall"
# after_app_uninstall = "sejel_app.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "sejel_app.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["sejel_app.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"sejel_app.tasks.all"
# 	],
# 	"daily": [
# 		"sejel_app.tasks.daily"
# 	],
# 	"hourly": [
# 		"sejel_app.tasks.hourly"
# 	],
# 	"weekly": [
# 		"sejel_app.tasks.weekly"
# 	],
# 	"monthly": [
# 		"sejel_app.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "sejel_app.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "sejel_app.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "sejel_app.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["sejel_app.utils.before_request"]
# after_request = ["sejel_app.utils.after_request"]

# Job Events
# ----------
# before_job = ["sejel_app.utils.before_job"]
# after_job = ["sejel_app.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"sejel_app.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

