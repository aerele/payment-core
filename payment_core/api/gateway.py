# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Shared shape for gateway settings controllers. Both pieces are opt-in: the
# Protocol is structural (every existing gateway already conforms) and the mixin
# adds no Document overrides, so adopting them changes no behaviour.

from typing import Protocol, runtime_checkable


@runtime_checkable
class PaymentGatewayController(Protocol):
	"""The V1 controller contract ERPNext calls on a gateway settings doc.

	on_payment_authorized is intentionally absent — it lives on the *reference*
	document, not the gateway controller.
	"""

	def get_payment_url(self, **kwargs) -> str: ...

	def validate_transaction_currency(self, currency: str) -> None: ...


class GatewayControllerMixin:
	"""Opt-in shared helpers for gateway settings controllers.

	Adopt by inheriting before Document, e.g.
	``class XSettings(GatewayControllerMixin, Document)``. Defines no
	``__init__``/Document overrides, so Frappe's controller instantiation is
	unaffected and other gateways are free to adopt it independently.
	"""

	def get_checkout_url(self, **kwargs):
		"""Convenience alias for the gateway's payment URL."""
		return self.get_payment_url(**kwargs)
