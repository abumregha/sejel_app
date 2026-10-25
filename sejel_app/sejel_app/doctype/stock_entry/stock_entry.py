import frappe
from frappe.model.document import Document


class StockEntry(Document):
	def validate(self):
		self.calculate_total()

	def calculate_total(self):
		total = 0
		for detail in self.get("details", []):
			qty = float(detail.quantity or 0)
			price = float(detail.unit_price or 0)
			detail.amount = qty * price
			total += detail.amount
		self.total_amount = total

	def on_submit(self):
		self.status = "submitted"
		self._apply_to_deposit()

	def on_cancel(self):
		self.status = "cancelled"
		self._revert_deposit()

	def _apply_to_deposit(self):
		if self.entry_type not in ("delivery", "rent"):
			return
		remaining = float(self.total_amount or 0)
		if remaining <= 0:
			return
		deposits = frappe.get_all(
			"Station Deposit",
			filters={"station": self.station},
			fields=["name", "balance"],
			order_by="deposit_date",
		)
		for dep in deposits:
			if remaining <= 0:
				break
			available = float(dep.balance or 0)
			if available <= 0:
				continue
			deducted = min(available, remaining)
			frappe.db.set_value("Station Deposit", dep.name, "allocated_amount",
				float(frappe.db.get_value("Station Deposit", dep.name, "allocated_amount") or 0) + deducted)
			remaining -= deducted

	def _revert_deposit(self):
		if self.entry_type not in ("delivery", "rent"):
			return
		to_revert = float(self.total_amount or 0)
		if to_revert <= 0:
			return
		deposits = frappe.get_all(
			"Station Deposit",
			filters={"station": self.station},
			fields=["name", "allocated_amount"],
			order_by="deposit_date",
		)
		for dep in deposits:
			if to_revert <= 0:
				break
			allocated = float(dep.allocated_amount or 0)
			if allocated <= 0:
				continue
			revert_amount = min(allocated, to_revert)
			frappe.db.set_value("Station Deposit", dep.name, "allocated_amount", allocated - revert_amount)
			to_revert -= revert_amount
