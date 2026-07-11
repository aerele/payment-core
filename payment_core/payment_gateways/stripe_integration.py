# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Compatibility shim: ERPNext Payment Request still imports
# ``payment_core.payment_gateways.stripe_integration.create_stripe_subscription``.
# Prefer ``payment_core.api.subscriptions.create_gateway_subscription`` going forward.

from payment_core.api.subscriptions import create_gateway_subscription


def create_stripe_subscription(gateway_controller, data):
	"""Delegate to the stripe_payment handler registered via hooks."""
	return create_gateway_subscription("stripe", gateway_controller, data)
