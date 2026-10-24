# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from payment_core.payment_ledger.status_flow import PaymentTransactionStatus
from payment_core.utils import (
	email_flow_enabled,
	get_customer_doctype,
	resolve_gateway_controller,
	send_payment_email,
)


# DocType hooks run inside the framework's request transaction; commits are
# owned by the calling endpoint, not the controller.
class PaymentTransaction(Document):
	"""Payment attempt linked to any Frappe document (Payment Request-style
	lifecycle: Draft -> Requested on submit, receipts drive Paid/Partially Paid)."""

	def validate(self):
		if self.customer and not self.customer_doctype:
			# Dynamic Links need their typing field
			self.customer_doctype = get_customer_doctype()
		if not self.transaction_date:
			self.transaction_date = frappe.utils.today()
		self.outstanding_amount = self.get_outstanding_amount()

	def before_submit(self):
		# here, not on_submit: frappe persists the row before on_submit runs
		if not self.gateway:
			frappe.throw(_("A payment gateway is required to submit a transaction"))
		if flt(self.amount) <= 0:
			frappe.throw(_("Payment amount must be greater than zero"))
		if not self.status or self.status == PaymentTransactionStatus.DRAFT:
			self.status = PaymentTransactionStatus.REQUESTED
		if PaymentTransactionStatus.is_open(self.status):
			self.create_payment_url()

	def on_submit(self):
		self.queue_payment_email()

	def queue_payment_email(self):
		"""Send the checkout link to the buyer; only on initial submission."""
		if self.status == "Requested" and self.checkout_url and email_flow_enabled():
			transaction = self.name
			frappe.db.after_commit(lambda: send_payment_email(transaction))

	def create_payment_url(self) -> str:
		"""Resolve the gateway checkout URL (idempotent)."""
		if self.checkout_url:
			return self.checkout_url
		controller = resolve_gateway_controller(self.gateway)
		if not controller:
			frappe.throw(_("Gateway {0} could not be resolved").format(frappe.bold(self.gateway)))
		url = controller.get_payment_url(
			amount=flt(self.amount),
			title=self.payer_name or self.reference_docname,
			description=self.subject
			or _("Payment for {0} {1}").format(self.reference_doctype, self.reference_docname),
			reference_doctype=self.reference_doctype,
			reference_docname=self.reference_docname,
			payer_email=self.customer_email,
			payer_name=self.payer_name,
			order_id=self.order_id or self.reference_docname,
			currency=self.currency,
			payment_transaction=self.name,
		)
		self.checkout_url = url
		return url

	def before_cancel(self):
		# settled money cannot be cancelled away - refund instead; with
		# auto_receipt off a Paid row has no receipts, so check the status too
		if PaymentTransactionStatus.is_settled(self.status):
			frappe.throw(_("A settled transaction cannot be cancelled. Refund it instead."))
		if frappe.db.exists("Payment Receipt", {"payment_transaction": self.name, "docstatus": 1}):
			frappe.throw(
				_("Transaction {0} has submitted Payment Receipts. Cancel them first.").format(
					frappe.bold(self.name)
				)
			)

	def set_status(
		self, status: str, *, from_receipts: bool = False, extra_values: dict | None = None
	) -> bool:
		"""Single status write-point for this document."""
		return PaymentTransactionStatus.set_status(
			self.name, status, from_receipts=from_receipts, extra_values=extra_values
		)

	def on_cancel(self):
		# guarded db write: frappe persists the row before on_cancel runs
		self.set_status(PaymentTransactionStatus.CANCELLED)

	def get_outstanding_amount(self) -> float:
		"""Amount minus submitted capture receipts."""
		if not self.name:
			return flt(self.amount)
		captured = sum(
			flt(amount)
			for amount in frappe.get_all(
				"Payment Receipt",
				filters={
					"payment_transaction": self.name,
					"entry_type": "Capture",
					"docstatus": 1,
				},
				pluck="amount",
			)
		)
		return flt(self.amount) - captured

	def on_trash(self):
		if frappe.db.exists("Payment Receipt", {"payment_transaction": self.name}):
			frappe.throw(
				_("Transaction {0} has Payment Receipts. Cancel it instead of deleting.").format(
					frappe.bold(self.name)
				)
			)
