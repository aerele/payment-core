# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Install/uninstall for the shared Web Form payment fields (gateway-agnostic).

import click
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

WEB_FORM_FIELDS = {
	"Web Form": [
		{
			"fieldname": "payments_tab",
			"fieldtype": "Tab Break",
			"label": "Payments",
			"insert_after": "custom_css",
			"module": "Payment Core",
		},
		{
			"default": "0",
			"fieldname": "accept_payment",
			"fieldtype": "Check",
			"label": "Accept Payment",
			"insert_after": "payments",
			"module": "Payment Core",
		},
		{
			"depends_on": "accept_payment",
			"fieldname": "payment_gateway",
			"fieldtype": "Link",
			"label": "Payment Gateway",
			"options": "Payment Gateway",
			"insert_after": "accept_payment",
			"module": "Payment Core",
		},
		{
			"default": "Buy Now",
			"depends_on": "accept_payment",
			"fieldname": "payment_button_label",
			"fieldtype": "Data",
			"label": "Button Label",
			"insert_after": "payment_gateway",
			"module": "Payment Core",
		},
		{
			"depends_on": "accept_payment",
			"fieldname": "payment_button_help",
			"fieldtype": "Text",
			"label": "Button Help",
			"insert_after": "payment_button_label",
			"module": "Payment Core",
		},
		{
			"fieldname": "payments_cb",
			"fieldtype": "Column Break",
			"insert_after": "payment_button_help",
			"module": "Payment Core",
		},
		{
			"default": "0",
			"depends_on": "accept_payment",
			"fieldname": "amount_based_on_field",
			"fieldtype": "Check",
			"label": "Amount Based On Field",
			"insert_after": "payments_cb",
			"module": "Payment Core",
		},
		{
			"depends_on": "eval:doc.accept_payment && doc.amount_based_on_field",
			"fieldname": "amount_field",
			"fieldtype": "Select",
			"label": "Amount Field",
			"insert_after": "amount_based_on_field",
			"module": "Payment Core",
		},
		{
			"depends_on": "eval:doc.accept_payment && !doc.amount_based_on_field",
			"fieldname": "amount",
			"fieldtype": "Currency",
			"label": "Amount",
			"insert_after": "amount_field",
			"module": "Payment Core",
		},
		{
			"depends_on": "accept_payment",
			"fieldname": "currency",
			"fieldtype": "Link",
			"label": "Currency",
			"options": "Currency",
			"insert_after": "amount",
			"module": "Payment Core",
		},
	]
}


def before_install():
	from payment_core.utils import before_install as _guard

	return _guard()


def after_install():
	if not frappe.get_meta("Web Form").has_field("payments_tab"):
		click.secho("* Installing Payment Web Form custom fields")
		create_custom_fields(WEB_FORM_FIELDS)
		frappe.clear_cache(doctype="Web Form")


def before_uninstall():
	if not frappe.get_meta("Web Form").has_field("payments_tab"):
		return
	click.secho("* Uninstalling Payment Web Form custom fields")
	frappe.db.delete(
		"Custom Field",
		{"dt": "Web Form", "fieldname": ("in", [f["fieldname"] for f in WEB_FORM_FIELDS["Web Form"]])},
	)
	frappe.clear_cache(doctype="Web Form")
