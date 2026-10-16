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
# nosemgrep: rules.frappe-modifying-but-not-comitting
class PaymentTransaction(Document):
	"""Provider-independent payment attempt linked to any Frappe document.

	Mirrors ERPNext's Payment Request lifecycle: created as Draft, submission
	marks it Requested and creates the payment URL at the gateway, receipts
	drive Paid / Partially Paid, cancelling is blocked once money is booked.
	"""

	def validate(self):
		if self.customer and not self.customer_doctype:
			# Dynamic Links need their typing field; default it from the
			# consuming app's payment_customer_doctype hook when set manually.
			self.customer_doctype = get_customer_doctype()
		if not self.transaction_date:
			self.transaction_date = frappe.utils.today()
		self.outstanding_amount = self.get_outstanding_amount()

	def before_submit(self):
		"""Validate, then resolve the checkout URL - here, not in on_submit.

		Frappe persists db_update() *before* on_submit runs
		(frappe/model/document.py), so field assignments made in on_submit
		survive only when something else rewrites them (the gateway sync
		layer happened to do that). Resolving in before_submit makes the
		Requested status + checkout URL durable by construction, matching
		ERPNext Payment Request's set_payment_request_url placement.
		"""
		if not self.gateway:
			frappe.throw(_("A payment gateway is required to submit a transaction"))
		if flt(self.amount) <= 0:
			frappe.throw(_("Payment amount must be greater than zero"))
		if not self.status or self.status == PaymentTransactionStatus.DRAFT:
			self.status = PaymentTransactionStatus.REQUESTED
		if PaymentTransactionStatus.is_open(self.status):
			self.create_payment_url()

	def on_submit(self):  # nosemgrep: rules.frappe-modifying-but-not-comitting
		"""After the row is durable as Requested: queue the buyer email."""
		self.queue_payment_email()

	def queue_payment_email(self):
		"""Email the buyer the checkout link when the email flow is enabled.

		ERPNext Payment Request parity: the link plus the reference
		document's print go to the buyer instead of being opened at the
		desk. Only the initial Requested submission emails - the gateway's
		late Draft auto-submit on Paid never does.
		"""
		if self.status == "Requested" and self.checkout_url and email_flow_enabled():
			transaction = self.name
			frappe.db.after_commit(lambda: send_payment_email(transaction))

	def create_payment_url(self) -> str:
		"""Create the gateway checkout URL for this transaction (idempotent)."""
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
		# ERPNext Payment Request parity: money that has been booked cannot be
		# cancelled away; cancel/amend the receipts first.
		if frappe.db.exists("Payment Receipt", {"payment_transaction": self.name, "docstatus": 1}):
			frappe.throw(
				_("Transaction {0} has submitted Payment Receipts. Cancel them first.").format(
					frappe.bold(self.name)
				)
			)

	def on_cancel(self):  # nosemgrep: rules.frappe-modifying-but-not-comitting
		# db_set, not assignment: frappe persists the row *before* on_cancel
		# runs (frappe/model/document.py: db_update precedes run_post_save_methods)
		# so a plain self.status write would never reach the database
		self.db_set("status", PaymentTransactionStatus.CANCELLED)

	def get_outstanding_amount(self) -> float:
		"""Amount minus submitted capture receipts for this transaction."""
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
