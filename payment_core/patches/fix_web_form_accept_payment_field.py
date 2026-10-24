# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Move the Web Form ``accept_payment`` custom field into the Payments tab.

Earlier installs anchored the field to ``payments`` — a fieldname that does
not exist on Web Form — so the field landed at the end of the form instead
of inside the Payments tab. New installs anchor to ``payments_tab`` directly
(see ``install.WEB_FORM_FIELDS``); this patch converges existing sites.
"""

import frappe


def execute():
	field = frappe.db.get_value(
		"Custom Field",
		{"dt": "Web Form", "fieldname": "accept_payment"},
		["name", "insert_after"],
		as_dict=True,
	)
	if not field or field.insert_after == "payments_tab":
		return
	frappe.db.set_value("Custom Field", field.name, "insert_after", "payments_tab")
