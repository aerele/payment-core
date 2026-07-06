# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Registry for gateway service modules. Gateway apps register via the
# `payment_gateway_module` hook, e.g. {"Stripe": "stripe_payment.gateway"}.

import importlib

import frappe


def get(gateway):
	"""Return the service module a gateway app registered for a gateway name."""
	registry = frappe.get_hooks("payment_gateway_module") or {}
	path = registry.get(gateway)
	if isinstance(path, list | tuple):
		path = path[-1]
	if not path:
		frappe.throw(frappe._("No service module registered for gateway '{0}'.").format(gateway))
	return importlib.import_module(path)
