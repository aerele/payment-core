# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Existing sites keep the Web Form accept_payment field anchored to the old
# "payments" section; re-anchor it to payments_tab so new installs and old
# sites render the payment fields in the same place.

import frappe


def execute():
	if frappe.db.exists("Custom Field", "Web Form-accept_payment"):
		frappe.db.set_value("Custom Field", "Web Form-accept_payment", "insert_after", "payments_tab")
