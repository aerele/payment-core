// Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
// License: MIT. See LICENSE

// Desk action: create a mapped Payment Transaction from any reference
// document whose doctype carries an enabled Payment Field Mapping. The list
// ships in boot (payment_core.boot.extend_bootinfo), so no per-form lookup.

$(document).on("form-refresh", (_event, frm) => {
	if (!(frappe.boot.payment_reference_doctypes || []).includes(frm.doctype)) {
		return;
	}
	if (frm.doc.docstatus === 2) {
		return;
	}
	frm.add_custom_button(
		__("Create Payment Transaction"),
		() => open_gateway_dialog(frm),
		__("Payments")
	);
});

function open_gateway_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Create Payment Transaction"),
		fields: [
			{
				fieldname: "gateway",
				fieldtype: "Link",
				label: __("Payment Gateway"),
				options: "Payment Gateway",
				reqd: 1,
			},
		],
		primary_action_label: __("Create"),
		primary_action: (values) => {
			dialog.hide();
			frappe
				.xcall("payment_core.utils.create_transaction_for_reference", {
					reference_doctype: frm.doctype,
					reference_docname: frm.doc.name,
					gateway: values.gateway,
				})
				.then((transaction) => {
					frappe.show_alert({
						message: __("Payment Transaction {0} created", [transaction]),
						indicator: "green",
					});
					frappe.set_route("Form", "Payment Transaction", transaction);
				});
		},
	});
	dialog.show();
}
