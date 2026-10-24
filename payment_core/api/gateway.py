# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Structural shape for gateway settings controllers; adopting either piece
# changes no behaviour.

from typing import Protocol, runtime_checkable


@runtime_checkable
class PaymentGatewayController(Protocol):
	"""Required V1 contract called on a gateway settings doc:
	get_payment_url (checkout URL; kwargs per
	PaymentTransaction.create_payment_url) and validate_transaction_currency
	(throw frappe.ValidationError for unsupported currencies).

	on_payment_authorized lives on the *reference* document, not here.
	"""

	def get_payment_url(self, **kwargs) -> str: ...

	def validate_transaction_currency(self, currency: str) -> None: ...


@runtime_checkable
class OptionalPaymentGatewayController(Protocol):
	"""Optional capabilities, hasattr-probed by callers - a gateway that does
	not offer one simply does not define it. Kept separate from
	PaymentGatewayController so runtime isinstance checks stay optional-safe.

	- reconcile_transaction(transaction) -> None: re-confirm an open
	  transaction at the provider and settle via update_payment_transaction.
	- refund_transaction(transaction, amount, reason, idempotency_key=None)
	  -> str: provider refund id for the Refund Payment Receipt; the key
	  lets the provider dedupe retried calls (double-refund guard).
	- get_charged_amount(payment_request) -> float: the amount of THIS
	  payment, straight from the provider (not a running total).
	- annotate_payment_entry(payment_entry, payment_request) -> None: copy
	  provider references onto an ERPNext Payment Entry.
	- process_webhook_log(log_name) -> None: re-run a Failed webhook's
	  processor (desk retry).
	"""

	def reconcile_transaction(self, transaction: str) -> None: ...

	def refund_transaction(
		self, transaction: str, amount: float, reason: str, idempotency_key: str | None = None
	) -> str: ...

	def get_charged_amount(self, payment_request) -> float: ...

	def annotate_payment_entry(self, payment_entry, payment_request) -> None: ...

	def process_webhook_log(self, log_name: str) -> None: ...


class GatewayControllerMixin:
	"""Opt-in helpers for gateway settings controllers; inherit before
	Document (no __init__/Document overrides)."""

	def get_checkout_url(self, **kwargs):
		return self.get_payment_url(**kwargs)
