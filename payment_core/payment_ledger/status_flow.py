# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""The Payment Transaction status lifecycle - one controller owns it all.

Modeled on ERPNext's status controllers (``erpnext/controllers/status_updater.py``):
the vocabulary, the classification helpers and the transition table live in a
single class, and every status write — the doctype controller, the gateway
sync boundary in ``utils``, the receipt sync and the scheduler expiry — goes
through it. The consequence: a late or out-of-order webhook can never regress
a settled transaction (``Paid -> Initiated`` is ignored, not applied), and
the one sanctioned regression (every capture cancelled) must declare itself
via ``via_cancellation``.
"""

from typing import ClassVar

import frappe
from frappe import _

from payment_core.notifications import WATCHED_STATUSES, on_transaction_update


class PaymentTransactionStatus:
	"""Base controller for the Payment Transaction status lifecycle."""

	DRAFT = "Draft"
	REQUESTED = "Requested"
	INITIATED = "Initiated"
	PARTIALLY_PAID = "Partially Paid"
	PAID = "Paid"
	FAILED = "Failed"
	CANCELLED = "Cancelled"
	REFUNDED = "Refunded"

	ALL = (DRAFT, REQUESTED, INITIATED, PARTIALLY_PAID, PAID, FAILED, CANCELLED, REFUNDED)
	# money has not settled yet; these are the rows reconcile/expire touch
	OPEN = (DRAFT, REQUESTED, INITIATED)
	# money moved; only receipt cancellations may leave these states
	SETTLED = (PARTIALLY_PAID, PAID, REFUNDED)
	# no forward move exists from here
	TERMINAL = (CANCELLED,)

	# Forward-only lifecycle: what each status may still become. A late
	# capture after an expiry-fail (Failed -> Paid/Partially Paid) and a
	# re-capture after a refund (Refunded -> Paid/Partially Paid) are the
	# deliberate "money arrived anyway" exceptions.
	FORWARD: ClassVar[dict[str, frozenset[str]]] = {
		DRAFT: frozenset({REQUESTED, INITIATED, PARTIALLY_PAID, PAID, FAILED, CANCELLED}),
		REQUESTED: frozenset({INITIATED, PARTIALLY_PAID, PAID, FAILED, CANCELLED}),
		INITIATED: frozenset({PARTIALLY_PAID, PAID, FAILED, CANCELLED}),
		PARTIALLY_PAID: frozenset({PAID, REFUNDED}),
		PAID: frozenset({REFUNDED}),
		REFUNDED: frozenset({PARTIALLY_PAID, PAID}),
		FAILED: frozenset({PARTIALLY_PAID, PAID}),
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
		"""Whether ``previous -> new`` keeps the lifecycle moving forward.

		An unset previous status and same-status writes are always allowed
		(the latter are routine idempotent re-deliveries).
		"""
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
	def apply(
		cls,
		transaction_name: str,
		new_status: str,
		*,
		via_cancellation: bool = False,
		extra_values: dict | None = None,
	) -> bool:
		"""Guarded status write; returns whether the status changed.

		Non-forward transitions are ignored (with a log line), not thrown:
		gateway events legitimately arrive out of order, and failing the
		request would only send the provider into a redelivery loop. The
		single exception is the receipt-cancellation regression — when every
		capture has been cancelled, a settled transaction returns to
		Initiated by design.
		"""
		previous = frappe.db.get_value("Payment Transaction", transaction_name, "status") or None
		if previous == new_status:
			return False
		sanctioned_regression = via_cancellation and previous in cls.SETTLED and new_status == cls.INITIATED
		if not cls.allows(previous, new_status) and not sanctioned_regression:
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
			# db.set_value bypasses doc_events; the Payment Manager alert
			# must fire here - this is the path failures actually take
			on_transaction_update(frappe.get_doc("Payment Transaction", transaction_name))
		return True


# module-level aliases so existing importers keep working
OPEN_TRANSACTION_STATUSES = PaymentTransactionStatus.OPEN
SETTLED_TRANSACTION_STATUSES = PaymentTransactionStatus.SETTLED
PAYMENT_TRANSACTION_STATUSES = frozenset(PaymentTransactionStatus.ALL)
