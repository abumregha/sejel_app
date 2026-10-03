import frappe
from datetime import datetime, timedelta
from frappe.model.document import Document


def _wall_clock_value(v):
	"""True when a Time value looks like the wall-clock stamp Frappe puts on
	fresh inserts instead of honoring a static default."""
	try:
		if isinstance(v, str):
			v = datetime.strptime(v.strip(), "%H:%M:%S.%f").time()
		now = frappe.utils.now_datetime().time()
		d = datetime.combine(datetime.today(), v) - datetime.combine(datetime.today(), now)
		return abs(d.total_seconds()) <= 180
	except Exception:
		return False


class Station(Document):
	def validate(self):
		# Frappe "Time" fields ignore static JSON defaults and stamp the insert
		# wall-clock instead — so a *provided* time that looks like a wall-clock
		# stamp is replaced with the intended 23:00 default.
		#
		# A station that deliberately has NO cycle is left unset: the reading
		# screens and the dashboard fall back to 23:00 at read time and SAY SO
		# («لم يتم ضبط وقت إقفال اليوم لهذه المحطة»). Forcing 23:00 into the
		# record made that warning unreachable and left an operator who cleared
		# the field staring at a silent 23:00 with no explanation anywhere.
		stamped = self.get("__islocal") and self.get("day_close_time") and _wall_clock_value(self.get("day_close_time"))
		if stamped:
			self.day_close_time = "23:00:00"
		elif not self.get("day_close_time"):
			self.day_close_time = None
		# Station docnames are hashes, so the name field needs an explicit guard
		# (the wizard endpoint has the same check; this protects the plain form).
		dup = frappe.db.get_value(
			"Station", {"station_name": self.station_name}, ["name", "station_name"], as_dict=True
		)
		if dup and dup.name != self.name:
			frappe.throw("يوجد محطة بنفس الاسم: {}".format(self.station_name))
