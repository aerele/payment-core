// Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
// License: MIT. See LICENSE

// List pill: the payment lifecycle status (Draft → Paid/Refunded), not the
// docstatus ("Submitted"). The palette is the single source shared with the
// form header indicator (payment_transaction.js re-imports it below).

frappe.listview_settings["Payment Transaction"] = {
	add_fields: ["status"],
	has_indicator_for_draft: true,
	has_indicator_for_cancelled: true,
	get_indicator(doc) {
		// the form script publishes the shared palette; a local copy keeps
		// the list correct when the form script has not loaded yet
		const colors = (frappe.payment_core_status_colors ||= {
			Draft: "grey",
			Requested: "orange",
			Initiated: "grey",
			"Partially Paid": "yellow",
			Paid: "green",
			Failed: "red",
			Cancelled: "grey",
			Refunded: "purple",
		});
		return [__(doc.status), colors[doc.status] || "grey", "status,=," + doc.status];
	},
};
