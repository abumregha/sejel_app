import frappe
from frappe.model.document import Document


class ReadingDeletionLog(Document):
	"""Append-only trail of deleted meter readings.

	Frappe removes a document's `Version` rows along with it, so a deleted
	reading used to leave no trace at all — no way to answer "who removed this,
	when, and what did it say?". MeterReading.on_trash writes one row here
	before the reading disappears; nothing in the UI edits or deletes these.
	"""

	pass
