# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Install/uninstall for the shared Web Form payment fields (gateway-agnostic).

import click
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from payment_core.mode import gateway_only_reason, is_gateway_only
from payment_core.utils import before_install as utils_before_install

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
			"insert_after": "payments_tab",
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
	return utils_before_install()


# Desk roles: Manager mirrors ERPNext's Accounts Manager, User mirrors Accounts User.
PAYMENT_ROLES = ("Payment Manager", "Payment User")


def ensure_default_roles():
	"""Create the desk roles used by apps adopting the payment doctypes."""
	for role_name in PAYMENT_ROLES:
		if not frappe.db.exists("Role", role_name):
			frappe.get_doc({"doctype": "Role", "role_name": role_name, "desk_access": 1}).insert(
				ignore_permissions=True
			)


def after_install():
	ensure_default_roles()
	if not frappe.get_meta("Web Form").has_field("payments_tab"):
		click.secho("* Installing Payment Web Form custom fields")
		create_custom_fields(WEB_FORM_FIELDS)
		frappe.clear_cache(doctype="Web Form")
	print_install_summary()


def print_install_summary():
	"""Tell the installing admin, right in the terminal, what just landed.

	On a site without ERPNext (or any own-flow app) the shared Payment Ledger
	is installed; on a site with one, payment_core stays a gateway layer.
	"""
	if is_gateway_only():
		click.secho("* Payment Core installed in gateway-only mode", fg="yellow")
		click.secho(f"  {gateway_only_reason()}")
		click.secho("  The shared Payment Ledger is NOT installed: the flow above keeps")
		click.secho("  owning documents and settlement. Payment Core provides the gateway")
		click.secho("  registry, hosted checkout, webhook verification and analytics only.")
		return

	click.secho("* No ERPNext found - installed the shared Payment Ledger", fg="green")
	summary = [
		(
			"Payment Transaction",
			"one row per payment attempt: reference document, amount, gateway,",
		),
		("", "status (Draft -> Requested -> Paid) and the hosted-checkout link"),
		(
			"Payment Receipt",
			"the money voucher written on capture/refund; drives Paid/Partially Paid",
		),
		(
			"Payment Field Mapping",
			"connects any doctype's fields to payment purposes (amount, buyer",
		),
		("", "email, phone, ...) - the doctype then gets the payment desk action"),
		(
			"Payment Gateway",
			"registry routing gateway rows to their settings (e.g. Stripe Settings)",
		),
		(
			"Payment Webhook Log",
			"audit of signed gateway webhooks (settlement backstop)",
		),
		(
			"Payment Core Settings",
			"site options: auto payment receipts, buyer email flow",
		),
	]
	for name, line in summary:
		click.secho(f"  - {name + ':':<24}{line}")
	click.secho("  Plus the Payment Core workspace and payment analytics.")
	click.secho("  Gateway apps (stripe_payment, ...) plug in as the checkout providers.")


def before_uninstall():
	if not frappe.get_meta("Web Form").has_field("payments_tab"):
		return
	click.secho("* Uninstalling Payment Web Form custom fields")
	frappe.db.delete(
		"Custom Field",
		{"dt": "Web Form", "fieldname": ("in", [f["fieldname"] for f in WEB_FORM_FIELDS["Web Form"]])},
	)
	frappe.clear_cache(doctype="Web Form")
