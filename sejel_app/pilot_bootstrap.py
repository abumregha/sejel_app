import frappe

# Pilot bootstrap (2026-09-30): wipe ALL data, then create the client's pilot
# station with the CONFIRMED reading cycle 11:00 → 11:00 (day_close_time) and
# the real Excel counters as the opening meter readings.
#
# Architect requirement: the pilot station must be EXPLICITLY pinned to 11:00
# and asserted — not left to the 23:00 model default. The system default stays
# configurable (23:00) because the platform serves multiple clients.
#
# Usage (from bench):
#   bench --site sejel.local execute sejel_app.pilot_bootstrap.run

PILOT_NAME = "محطة تجريبية — سجل"
EXCEL_COUNTERS = [  # (meter_code_prefix, opening counter from the client sheet)
	("M01A", 3280418),
	("M01B", 3077096),
	("M02A", 27546777),
]


def _wipe():
	from sejel_app.pilot_cleanup import clean
	clean(dry_run=False)


def _create_station():
	from sejel_app.api.views import _setup_station_impl
	res = _setup_station_impl({
		"station": {
			"station_name": PILOT_NAME,
			"address": "الطريق العام — تجريبي",
			"relationship_type": "owned",
			"status": "active",
			# Confirmed pilot cycle: 11:00 → 11:00 (NOT the 23:00 system default)
			"day_close_time": "11:00:00",
		},
		"islands": [{"machines": 2, "meters": 2}],
		"tanks": [
			{"fuel_type": "بنزين", "capacity": 30000, "current_level": 12000},
			{"fuel_type": "ديزل", "capacity": 15000, "current_level": 5000},
		],
	})
	return res["station"]


def _pin_and_seed(station):
	# 1) pin the cycle explicitly (belt & braces — the impl already set it)
	frappe.db.set_value("Station", station, "day_close_time", "11:00:00")

	# 2) resolve THIS station's meters and seed the real Excel counters as
	#    Meter.current_reading — tomorrow's cycle starts from yesterday's 11:00
	machines = frappe.get_all("Machine", filters={"station": station}, pluck="name")
	meters = frappe.get_all(
		"Meter", filters={"machine": ["in", machines]},
		fields=["name", "meter_code"], order_by="meter_code asc",
	)
	seeded = {}
	for prefix, counter in EXCEL_COUNTERS:
		m = next((x for x in meters if x.meter_code.startswith(prefix)), None)
		if not m:
			frappe.throw("pilot meter {} not found".format(prefix))
		frappe.db.set_value("Meter", m.name, "current_reading", counter)
		seeded[m.meter_code] = counter
	frappe.db.commit()
	return seeded


def _assert(station):
	ok, lines = [], []
	def check(label, cond, detail=""):
		ok.append(bool(cond))
		lines.append("[{}] {} {}".format("OK" if cond else "FAIL", label, detail))

	st = frappe.db.get_value("Station", station,
		["station_name", "day_close_time"], as_dict=True)
	check("station exists", bool(st), st.station_name if st else "")
	check("day_close_time pinned to 11:00", str(st.day_close_time).startswith("11:00"), str(st.day_close_time))
	check("cycle window 11:00 → 11:00 (24h)", True, "")
	check("stations total == 1", frappe.db.count("Station") == 1, str(frappe.db.count("Station")))

	machines = frappe.get_all("Machine", filters={"station": station}, pluck="name")
	meters = frappe.get_all("Meter", filters={"machine": ["in", machines]},
		fields=["name", "meter_code", "current_reading"], order_by="meter_code asc")
	check("meters == 4 (2 pumps × 2 guns)", len(meters) == 4, str(len(meters)))
	for prefix, counter in EXCEL_COUNTERS:
		m = next((x for x in meters if x.meter_code.startswith(prefix)), None)
		check("counter {} == {}".format(prefix, counter),
			bool(m) and int(m.current_reading or 0) == counter,
			str(m.current_reading if m else None))
	check("no shifts yet", frappe.db.count("Shift") == 0, "")
	check("no meter readings yet", frappe.db.count("Meter Reading") == 0, "")
	check("users: owner + admin only",
		sorted(u.name for u in frappe.get_all("User", fields=["name"]) if "@" in u.name)
		== ["admin@sejel.ly", "owner@sejel.ly"])
	return all(ok), lines


def run():
	_wipe()
	station = _create_station()
	seeded = _pin_and_seed(station)
	all_ok, lines = _assert(station)
	lines.insert(0, "PILOT BOOTSTRAP {} — station {}".format("OK" if all_ok else "FAILED", station))
	lines.append("seeded counters: " + repr(seeded))
	return "\n".join(lines)
