// Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
// License: MIT. See LICENSE

frappe.ui.form.on("Payment Transaction", {
	refresh(frm) {
		set_status_indicator(frm);
		show_checkout_link(frm);
		add_desk_actions(frm);
	},
});

function set_status_indicator(frm) {
	const colors = {
		Draft: "grey",
		Requested: "orange",
		Initiated: "grey",
		"Partially Paid": "yellow",
		Paid: "green",
		Failed: "red",
		Cancelled: "grey",
		Refunded: "purple",
	};
	const color = colors[frm.doc.status];
	if (color) {
		frm.page.set_indicator(frm.doc.status, color);
	}
}

function show_checkout_link(frm) {
	if (!frm.doc.checkout_url) {
		return;
	}
	frm.set_intro(__("A checkout session exists for this transaction."), "blue");
	frm.add_custom_button(__("Open Checkout"), () => window.open(frm.doc.checkout_url, "_blank"));
	if (
		frm.doc.docstatus === 1 &&
		!["Paid", "Failed", "Cancelled", "Refunded"].includes(frm.doc.status)
	) {
		frm.add_custom_button(__("Send Payment Email"), () => {
			frappe
				.call({
					method: "payment_core.utils.resend_payment_email",
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __("Sending payment link…"),
				})
				.then((r) => {
					if (r.message) {
						frappe.show_alert({
							message: __("Payment link emailed to {0}", [r.message]),
							indicator: "green",
						});
					}
				});
		});
	}
}

function add_desk_actions(frm) {
	// server lifecycle vocabulary (utils.OPEN_TRANSACTION_STATUSES)
	const open_statuses = ["Draft", "Requested", "Initiated"];
	if (!open_statuses.includes(frm.doc.status)) {
		return;
	}

	frm.add_custom_button(
		__("Mark Completed"),
		() => {
			frappe.prompt(
				{
					fieldname: "provider_reference",
					fieldtype: "Data",
					label: __("Provider Reference"),
					description: __(
						"Optional provider transaction id, e.g. the Stripe PaymentIntent."
					),
				},
				({ provider_reference }) => {
					frappe
						.call({
							method: "payment_core.utils.complete_payment_transaction",
							args: {
								name: frm.doc.name,
								provider_reference: provider_reference || "",
							},
							freeze: true,
							freeze_message: __("Settling payment…"),
						})
						.then(() => frm.reload_doc());
				},
				__("Mark Completed")
			);
		},
		__("Payment Transaction")
	);

	frm.add_custom_button(
		__("Cancel Transaction"),
		() => {
			frappe
				.call({
					method: "payment_core.utils.cancel_payment_transaction",
					args: { name: frm.doc.name },
				})
				.then(() => frm.reload_doc());
		},
		__("Payment Transaction")
	);
}
