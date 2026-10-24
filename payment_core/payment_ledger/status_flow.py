# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Payment Transaction status lifecycle: one table, one write-point (cf.
erpnext/controllers/status_updater.py). Every status write goes through
``set_status``; non-forward changes are ignored except receipt-driven writes."""

from typing import ClassVar

import frappe
from frappe import _

from payment_core.notifications import (
	WATCHED_STATUSES,
	alert_payment_managers,
	on_transaction_update,
)


class PaymentTransactionStatus:
	"""Controller for the Payment Transaction status lifecycle."""

	DRAFT = "Draft"
	REQUESTED = "Requested"
	INITIATED = "Initiated"
	PARTIALLY_PAID = "Partially Paid"
	PAID = "Paid"
	FAILED = "Failed"
	CANCELLED = "Cancelled"
	REFUNDED = "Refunded"

	ALL = (DRAFT, REQUESTED, INITIATED, PARTIALLY_PAID, PAID, FAILED, CANCELLED, REFUNDED)
	# rows reconcile/expire touch
	OPEN = (DRAFT, REQUESTED, INITIATED)
	# only receipt cancellations may leave these
	SETTLED = (PARTIALLY_PAID, PAID, REFUNDED)
	TERMINAL = (CANCELLED,)

	# Forward-only; deliberate exceptions: late capture (Failed ->
	# Paid/Partially Paid) and desk-cancel of a Failed attempt. Refunded is
	# terminal - a late "Paid" must not undo a refund.
	FORWARD: ClassVar[dict[str, frozenset[str]]] = {
		DRAFT: frozenset({REQUESTED, INITIATED, PARTIALLY_PAID, PAID, FAILED, CANCELLED}),
		REQUESTED: frozenset({INITIATED, PARTIALLY_PAID, PAID, FAILED, CANCELLED}),
		INITIATED: frozenset({PARTIALLY_PAID, PAID, FAILED, CANCELLED}),
		PARTIALLY_PAID: frozenset({PAID, REFUNDED}),
		PAID: frozenset({REFUNDED}),
		REFUNDED: frozenset(),
		FAILED: frozenset({PARTIALLY_PAID, PAID, CANCELLED}),
		CANCELLED: frozenset(),
	}

	@classmethod
	def is_open(cls, status: str | None) -> bool:
		return status in cls.OPEN

	@classmethod
	def is_settled(cls, status: str | None) -> bool:
		return status in cls.SETTLED

	@classmethod
	def is_terminal(cls, status: str | None) -> bool:
		return status in cls.TERMINAL

	@classmethod
	def allows(cls, previous: str | None, new: str) -> bool:
		"""Same-status writes are allowed (routine idempotent re-deliveries)."""
		if not previous or previous == new:
			return True
		return new in cls.FORWARD.get(previous, frozenset())

	@classmethod
	def assert_transition(cls, previous: str | None, new: str) -> None:
		if not cls.allows(previous, new):
			frappe.throw(
				_("Invalid payment status transition: {0} to {1}").format(
					frappe.bold(previous), frappe.bold(new)
				)
			)

	@classmethod
	def set_status(
		cls,
		transaction_name: str,
		new_status: str,
		*,
		from_receipts: bool = False,
		extra_values: dict | None = None,
	) -> bool:
		"""Guarded status write; returns whether the status changed.

		Non-forward changes are ignored, not thrown - throwing would only send
		the provider into a redelivery loop. ``from_receipts`` (the receipt
		sync) may set whatever its receipts justify, including regressing a
		settled transaction. ``extra_values`` are written even on a
		same-status update so derived values (``outstanding_amount``) never
		go stale.
		"""
		previous = frappe.db.get_value("Payment Transaction", transaction_name, "status") or None
		if previous == new_status:
			if extra_values:
				frappe.db.set_value(
					"Payment Transaction", transaction_name, extra_values, update_modified=False
				)
			return False
		if not cls.allows(previous, new_status) and not from_receipts:
			cls.alert_money_on_frozen_transaction(transaction_name, previous, new_status)
			frappe.logger("payment_core").info(
				"Ignored non-forward status change on %s: %s -> %s",
				transaction_name,
				previous,
				new_status,
			)
			return False
		values = {"status": new_status, **(extra_values or {})}
		frappe.db.set_value("Payment Transaction", transaction_name, values, update_modified=False)
		if new_status in WATCHED_STATUSES:
			# db.set_value bypasses doc_events
			on_transaction_update(frappe.get_cached_doc("Payment Transaction", transaction_name))
		return True

	@classmethod
	def alert_money_on_frozen_transaction(
		cls, transaction_name: str, previous: str | None, new_status: str
	) -> None:
		"""Alert when money lands on a transaction that cannot accept it.

		Only terminal (Cancelled) previous states: a stale event on a settled
		transaction is routine noise, and telling a manager to "decide
		whether to refund" for already-booked money invites mistakes."""
		if previous not in cls.TERMINAL or new_status not in (cls.PAID, cls.PARTIALLY_PAID):
			return
		message = (
			f"Payment Transaction {transaction_name} is {previous}, but the gateway reported "
			f"{new_status}. The payment was NOT booked - decide whether to refund it at the provider."
		)
		frappe.log_error(
			title="Payment received on frozen transaction",
			message=message,
			reference_doctype="Payment Transaction",
			reference_name=transaction_name,
		)
		alert_payment_managers(
			_("Payment {0} reported {1} after it was {2}").format(
				frappe.bold(transaction_name), frappe.bold(new_status), frappe.bold(previous)
			),
			transaction_name,
		)


# module-level aliases for existing importers
OPEN_TRANSACTION_STATUSES = PaymentTransactionStatus.OPEN
SETTLED_TRANSACTION_STATUSES = PaymentTransactionStatus.SETTLED
PAYMENT_TRANSACTION_STATUSES = frozenset(PaymentTransactionStatus.ALL)
