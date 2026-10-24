# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime

from payment_core.payment_ledger.status_flow import PaymentTransactionStatus
from payment_core.utils import authorize_reference, get_amount_precision, get_capture_balance

OPEN_STATUSES = ("Draft", "Requested", "Initiated")


# DocType hooks run inside the framework's request transaction; commits are
# owned by the calling endpoint, not the controller.
class PaymentReceipt(Document):
	"""One money movement against a reference document (Capture or Refund);
	submission drives the transaction's status."""

	def validate(self):
		if not self.posted_on:
			self.posted_on = now_datetime()
		if flt(self.amount) <= 0:
			frappe.throw(_("Receipt amount must be greater than zero"))
		if self.entry_type == "Capture":
			self.validate_capture_against_transaction()

	def validate_capture_against_transaction(self):
		"""A Capture must match its transaction: reference, currency, amount."""
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
		precision = get_amount_precision()
		outstanding = flt(
			flt(transaction.amount, precision)
			- flt(
				sum(
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
				),
				precision,
			),
			precision,
		)
		if flt(self.amount, precision) > outstanding:
			frappe.throw(
				_("Capture of {0} exceeds the outstanding amount of {1}").format(
					frappe.bold(self.amount), frappe.bold(outstanding)
				)
			)

	def before_submit(self):
		if self.entry_type == "Refund":
			self.validate_refund_balance()

	def validate_refund_balance(self):
		"""A refund may not exceed captured minus already refunded."""
		balance = get_capture_balance(self.reference_doctype, self.reference_docname, exclude_name=self.name)
		precision = get_amount_precision()
		if flt(self.amount, precision) > flt(balance["net"], precision):
			frappe.throw(
				_("Refund of {0} exceeds the refundable balance of {1} for {2} {3}").format(
					self.amount, balance["net"], self.reference_doctype, self.reference_docname
				)
			)

	def before_cancel(self):
		# a Capture backing refunds cannot be cancelled away either
		self.throw_if_capture_still_needed()

	def on_submit(self):
		self.sync_transaction_state()

	def on_cancel(self):
		self.sync_transaction_state()

	def throw_if_capture_still_needed(self):
		"""A Capture whose refunds still draw on it cannot leave the ledger."""
		if self.entry_type != "Capture" or not self.reference_doctype:
			return
		balance = get_capture_balance(self.reference_doctype, self.reference_docname, exclude_name=self.name)
		net = flt(balance["net"], get_amount_precision())
		if net < 0:
			frappe.throw(
				_("Cannot remove this Capture: {0} in refunds still relies on it").format(frappe.bold(-net))
			)

	def on_trash(self):
		self.throw_if_capture_still_needed()

	def after_delete(self):
		self.sync_transaction_state()

	def sync_transaction_state(self):
		"""Mirror submitted receipt activity onto the transaction:
		full capture -> Paid, partial -> Partially Paid, refunds covering
		captures -> Refunded, all captures cancelled -> Initiated."""
		if not self.payment_transaction or not frappe.db.exists(
			"Payment Transaction", self.payment_transaction
		):
			return
		transaction = frappe.get_cached_doc("Payment Transaction", self.payment_transaction)
		totals = {"Capture": 0.0, "Refund": 0.0}
		# system context: voucher submit computing settlement from sibling receipts
		for row in frappe.get_all(
			"Payment Receipt",
			filters={"payment_transaction": self.payment_transaction, "docstatus": 1},
			fields=["entry_type", "amount"],
		):
			totals[row.entry_type] = totals.get(row.entry_type, 0) + flt(row.amount)
		precision = get_amount_precision()
		captured = flt(totals["Capture"], precision)
		refunded = flt(totals["Refund"], precision)
		outstanding = flt(flt(transaction.amount, precision) - captured, precision)

		if captured <= 0:
			if PaymentTransactionStatus.is_settled(transaction.status):
				transaction.set_status(
					PaymentTransactionStatus.INITIATED,
					from_receipts=True,
					extra_values={"outstanding_amount": flt(transaction.amount, precision)},
				)
			return
		if refunded >= captured:
			new_status, new_outstanding = PaymentTransactionStatus.REFUNDED, 0
		elif outstanding > 0:
			new_status, new_outstanding = PaymentTransactionStatus.PARTIALLY_PAID, outstanding
		else:
			new_status, new_outstanding = PaymentTransactionStatus.PAID, 0
		applied = transaction.set_status(
			new_status,
			from_receipts=True,
			extra_values={"outstanding_amount": new_outstanding},
		)
		# a desk-booked Capture settles the reference too - exactly once per
		# transaction: a status returning to Paid (a cancelled Refund receipt)
		# must not fulfill the reference a second time
		if applied and new_status == PaymentTransactionStatus.PAID and not transaction.reference_authorized:
			transaction.db_set("reference_authorized", 1)
			authorize_reference(transaction.reference_doctype, transaction.reference_docname, "Paid")
