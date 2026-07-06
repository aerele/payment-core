# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Reassign the shared Payment Gateway doctype + Web Form payment fields to the
# payment_core app's "Payment Core" module on existing sites (data preserved).

import frappe

WEB_FORM_FIELDS = (
	"payments_tab",
	"accept_payment",
	"payment_gateway",
	"payment_button_label",
	"payment_button_help",
	"payments_cb",
	"amount_based_on_field",
	"amount_field",
	"amount",
	"currency",
)


def execute():
	if frappe.db.exists("DocType", "Payment Gateway"):
		frappe.db.set_value("DocType", "Payment Gateway", "module", "Payment Core", update_modified=False)

	for fieldname in WEB_FORM_FIELDS:
		name = frappe.db.get_value("Custom Field", {"dt": "Web Form", "fieldname": fieldname})
		if name:
			frappe.db.set_value("Custom Field", name, "module", "Payment Core", update_modified=False)
