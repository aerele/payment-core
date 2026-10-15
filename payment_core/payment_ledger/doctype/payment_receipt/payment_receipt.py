# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from payment_core.payment_ledger.status_flow import PaymentTransactionStatus
from payment_core.utils import get_capture_balance

OPEN_STATUSES = ("Draft", "Requested", "Initiated")


# DocType hooks run inside the framework's request transaction; commits are
# owned by the calling endpoint, not the controller.
# nosemgrep: rules.frappe-modifying-but-not-comitting
class PaymentReceipt(Document):
	"""One money movement against a reference document (Capture or Refund).

	Mirrors ERPNext's Payment Entry: a submittable voucher — booking the money
	happens on submit, and submission drives the transaction's status
	(Partially Paid / Paid / Refunded) automatically.
	"""

	def validate(self):
		if not self.posted_on:
			self.posted_on = now_datetime()
		if flt(self.amount) <= 0:
			frappe.throw(_("Receipt amount must be greater than zero"))
		if self.entry_type == "Capture":
			self.validate_capture_against_transaction()

	def validate_capture_against_transaction(self):
		"""A Capture must match its transaction: reference, currency and amount.

		Without this, a Capture could book money under a different reference,
		currency or an amount beyond the transaction and still drive it to
		Paid. Refunds get the balance check in before_submit; captures get
		theirs here.
		"""
		if not self.payment_transaction:
			return
		transaction = frappe.db.get_value(
			"Payment Transaction",
			self.payment_transaction,
			["reference_doctype", "reference_docname", "currency", "amount"],
			as_dict=True,
		)
		if not transaction:
			return
		if (self.reference_doctype, self.reference_docname) != (
			transaction.reference_doctype,
			transaction.reference_docname,
		):
			frappe.throw(
				_("Capture reference {0} {1} does not match transaction {2}").format(
					self.reference_doctype, frappe.bold(self.reference_docname), self.payment_transaction
				)
			)
		if self.currency and transaction.currency and self.currency != transaction.currency:
			frappe.throw(
				_("Capture currency {0} does not match transaction currency {1}").format(
					frappe.bold(self.currency), frappe.bold(transaction.currency)
				)
			)
		outstanding = flt(transaction.amount) - sum(
			flt(amount)
			# system context: controller validation reading sibling vouchers
			for amount in frappe.get_all(
				"Payment Receipt",
				filters={
					"payment_transaction": self.payment_transaction,
					"entry_type": "Capture",
					"docstatus": 1,
				},
				pluck="amount",
			)
		)
		if flt(self.amount) > outstanding:
			frappe.throw(
				_("Capture of {0} exceeds the outstanding amount of {1}").format(
					frappe.bold(self.amount), frappe.bold(outstanding)
				)
			)

	def before_submit(self):
		"""Re-check the refund balance against booked captures at submit time."""
		if self.entry_type == "Refund":
			self.validate_refund_balance()

	def validate_refund_balance(self):
		"""A refund may not exceed what was captured minus what was already refunded."""
		balance = get_capture_balance(self.reference_doctype, self.reference_docname, exclude_name=self.name)
		if flt(self.amount) > flt(balance["net"]):
			frappe.throw(
				_("Refund of {0} exceeds the refundable balance of {1} for {2} {3}").format(
					self.amount, balance["net"], self.reference_doctype, self.reference_docname
				)
			)

	def on_submit(self):  # nosemgrep: rules.frappe-modifying-but-not-comitting
		self.sync_transaction_state()

	def on_cancel(self):  # nosemgrep: rules.frappe-modifying-but-not-comitting
		self.sync_transaction_state()

	def on_trash(self):
		"""Keep the ledger consistent: a Capture backing refunds cannot vanish."""
		if self.entry_type != "Capture" or not self.reference_doctype:
			return
		balance = get_capture_balance(self.reference_doctype, self.reference_docname, exclude_name=self.name)
		if flt(balance["net"]) < 0:
			frappe.throw(
				_("Cannot delete this Capture: {0} in refunds still relies on it").format(
					frappe.bold(flt(-balance["net"]))
				)
			)

	def after_delete(self):
		self.sync_transaction_state()

	def sync_transaction_state(self):
		"""Mirror submitted receipt activity onto the transaction.

		Payment Entry → Payment Request parity: booking a receipt converts the
		transaction automatically.
		- full capture → Paid
		- captures short of the transaction amount → Partially Paid + outstanding
		- refunds fully offsetting captures → Refunded
		- all captures cancelled → back to the open Initiated state
		"""
		if not self.payment_transaction:
			return
		transaction = frappe.db.get_value(
			"Payment Transaction", self.payment_transaction, ["amount", "status"], as_dict=True
		)
		if not transaction:
			return
		totals = {"Capture": 0.0, "Refund": 0.0}
		# system context: voucher submit computing settlement from sibling receipts
		for row in frappe.get_all(
			"Payment Receipt",
			filters={"payment_transaction": self.payment_transaction, "docstatus": 1},
			fields=["entry_type", "amount"],
		):
			totals[row.entry_type] = totals.get(row.entry_type, 0) + flt(row.amount)
		captured, refunded = totals["Capture"], totals["Refund"]
		outstanding = flt(transaction.amount) - captured

		if captured <= 0:
			if PaymentTransactionStatus.is_settled(transaction.status):
				# the sanctioned regression: every capture was cancelled, so
				# the transaction returns to the open Initiated state
				PaymentTransactionStatus.apply(
					self.payment_transaction,
					PaymentTransactionStatus.INITIATED,
					via_cancellation=True,
					extra_values={"outstanding_amount": flt(transaction.amount)},
				)
			return
		if refunded >= captured:
			new_status, new_outstanding = PaymentTransactionStatus.REFUNDED, 0
		elif outstanding > 0:
			new_status, new_outstanding = PaymentTransactionStatus.PARTIALLY_PAID, outstanding
		else:
			new_status, new_outstanding = PaymentTransactionStatus.PAID, 0
		# the status controller guards the write (forward-only) and fires the
		# Payment Manager alert for watched statuses on a real transition
		PaymentTransactionStatus.apply(
			self.payment_transaction,
			new_status,
			extra_values={"outstanding_amount": new_outstanding},
		)
