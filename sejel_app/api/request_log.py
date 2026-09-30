# This runs on every request to verify
import frappe
import json

# Save debug info for every request hitting our app
try:
    with open("/tmp/frappe_all_requests.log", "a") as f:
        f.write(f"\n--- REQUEST ---\n")
        f.write(f"URL: {frappe.request.url}\n")
        f.write(f"Method: {frappe.request.method}\n")
        f.write(f"Content-Type: {frappe.request.content_type}\n")
        f.write(f"Data: {str(frappe.request.data)[:500] if frappe.request.data else 'None'}\n")
        f.write(f"Form Dict: {dict(frappe.form_dict)}\n")
        f.write(f"Session User: {frappe.session.user}\n")
except Exception as e:
    pass
