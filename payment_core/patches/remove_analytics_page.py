# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT

import frappe


def execute():
	"""Drop the standalone payment-analytics page.

	The workspace home renders the full analytics report through the
	"Payment Analytics" custom block (PR: workspace analytics home), so the
	separate page is a duplicate surface. Removing its fixture files does not
	delete the Page on sites that installed it earlier — this patch does.
	"""

	if frappe.db.exists("Page", "payment-analytics"):
		frappe.delete_doc("Page", "payment-analytics", force=True)
