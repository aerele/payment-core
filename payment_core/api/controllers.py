# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Canonical gateway-controller resolution shared across payment apps.

import frappe


def get_gateway_controller_name(reference_doctype=None, reference_docname=None, payment_gateway=None):
	"""Resolve a payment to its gateway controller docname.

	Returns the ``gateway_controller`` value of the linked Payment Gateway. This
	is the single source of truth behind the per-gateway ``get_gateway_controller``
	helpers. Distinct from ``get_payment_gateway_controller`` which returns the
	controller *Document*, not its name.
	"""
	if not payment_gateway:
		payment_gateway = frappe.get_doc(reference_doctype, reference_docname).payment_gateway
	return frappe.db.get_value("Payment Gateway", payment_gateway, "gateway_controller")
