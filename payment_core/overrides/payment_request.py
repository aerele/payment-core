# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Temporary shim: redirects ERPNext's Payment Request gateway resolution from
# the `payments` app to payment_core, until ERPNext changes it upstream.
# Rebinding the two module-level resolver helpers is enough — ERPNext's own
# methods resolve them at call time. Only `create_subscription` needs a class
# override (its payments import is function-local). The class is registered
# via `extend_doctype_class` (see hooks.py) so this module loads with the
# Payment Request controller; ERPNext's controller file stays pristine.

import erpnext.accounts.doctype.payment_request.payment_request as erpnext_payment_request

from payment_core.api.subscriptions import create_gateway_subscription
from payment_core.utils import get_payment_gateway_controller, is_v2_gateway

erpnext_payment_request._get_payment_gateway_controller = get_payment_gateway_controller
erpnext_payment_request._is_v2_gateway = is_v2_gateway


class PaymentRequest(erpnext_payment_request.PaymentRequest):
	"""Payment Request whose gateway resolution is owned by payment_core.

	Gateway resolution is redirected at module level (above); the class only
	overrides `create_subscription` (function-local payments import) and adds
	`validate` to stamp the gateway's Mode of Payment when the caller didn't
	set one — so it flows onto the Payment Entry through ERPNext's own copy
	in `create_payment_entry`.
	"""

	def validate(self):
		# stamp BEFORE super().validate() so ERPNext's own
		# validate_enabled_mode_of_payment also covers the stamped value
		self.set_default_mode_of_payment()
		super().validate()

	def set_default_mode_of_payment(self):
		"""Stamp the gateway's auto-created Mode of Payment when unset.

		ERPNext copies `self.mode_of_payment` onto the Payment Entry
		(payment_request.py create_payment_entry), which makes the gateway
		visible in Bank Reconciliation and POS reports. Only enabled Modes
		of Payment are stamped — a disabled one would make the Payment
		Entry fail after the buyer already paid.
		"""
		if self.mode_of_payment or not self.payment_gateway:
			return
		from payment_core.mode_of_payment import get_mode_of_payment_for_gateway

		mop = get_mode_of_payment_for_gateway(self.payment_gateway)
		if mop:
			self.mode_of_payment = mop

	def create_subscription(self, payment_provider, gateway_controller, data):
		# Dispatch via payment_core's registry, not payments.stripe_integration.
		return create_gateway_subscription(payment_provider, gateway_controller, data)
