# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Generic gateway-subscription dispatcher. ERPNext calls this; each gateway app
# registers its handler via the `gateway_subscription_handler` hook, e.g.
#   gateway_subscription_handler = {"stripe": "stripe_payment.gateway.subscriptions.create_stripe_subscription"}

import frappe
from frappe import _


def create_gateway_subscription(provider, gateway_controller, data):
	"""Route a subscription-creation request to the installed gateway app."""
	handler = (frappe.get_hooks("gateway_subscription_handler") or {}).get(provider)
	if not handler:
		frappe.throw(_("No subscription handler registered for gateway '{0}'.").format(provider))
	# frappe.get_hooks returns a list when merged across apps; take the last (app-overridable).
	dotted_path = handler[-1] if isinstance(handler, list | tuple) else handler
	return frappe.get_attr(dotted_path)(gateway_controller, data)
