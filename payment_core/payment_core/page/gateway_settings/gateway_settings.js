// Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
// License: MIT. See LICENSE

frappe.pages["gateway-settings"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Gateway Settings"),
		single_column: true,
	});
	const open_gateway_picker = () => {
		frappe
			.call({ method: "payment_core.workspace.get_gateway_settings_options" })
			.then((r) => {
				const options = r.message || [];
				if (!options.length) {
					frappe.msgprint({
						title: __("No gateway apps installed"),
						message: __(
							"Install a gateway app (stripe_payment, razorpay_payment, ...) first; its settings form registers the Payment Gateway for you."
						),
						indicator: "orange",
					});
					return;
				}
				const dialog = new frappe.ui.Dialog({
					title: __("Add a payment gateway"),
					indicator: "green",
					fields: [
						{
							fieldtype: "HTML",
							options:
								'<p class="gateway-picker-help">' +
								__(
									"Pick the gateway to configure. Saving its settings registers the payment gateway automatically - no manual Payment Gateway row needed."
								) +
								"</p>",
						},
						{
							fieldname: "gateway_type",
							fieldtype: "Link",
							label: __("Gateway Settings DocType"),
							options: "DocType",
							reqd: 1,
							get_query: () => ({
								filters: { name: ["in", options.map((option) => option.label)] },
							}),
						},
					],
					primary_action_label: __("Configure"),
					primary_action: (values) => {
						const chosen = options.find(
							(option) => option.label === values.gateway_type
						);
						dialog.hide();
						if (chosen) frappe.set_route(chosen.route);
					},
				});
				dialog.show();
			});
	};

	page.set_primary_action(__("Add Gateway"), open_gateway_picker);
	// escape hatch for gateways without an app: app-backed gateways register
	// their Payment Gateway row themselves on settings save
	page.set_secondary_action(__("Manual Payment Gateway"), () =>
		frappe.set_route("Form", "Payment Gateway", "new")
	);

	const render = (gateways) => {
		const cards = gateways
			.map((gateway) => {
				const health = gateway.healthy
					? '<span class="indicator green gateway-health-label">' +
					  __("Healthy") +
					  "</span>"
					: gateway.warnings
							.map(
								(w) =>
									'<div class="gateway-warning">' +
									frappe.utils.escape_html(w) +
									"</div>"
							)
							.join("");
				const safe_route = frappe.utils.escape_html(
					gateway.route
						.split("/")
						.map((segment) => encodeURIComponent(segment))
						.join("/")
				);
				return (
					'<div class="gateway-card">' +
					'<a href="' +
					safe_route +
					'" class="gateway-name">' +
					frappe.utils.escape_html(gateway.name) +
					"</a>" +
					'<div class="gateway-health">' +
					health +
					"</div>" +
					'<div class="gateway-configure"><a href="' +
					safe_route +
					'">' +
					__("Configure") +
					" &rarr;</a></div>" +
					"</div>"
				);
			})
			.join("");
		$(wrapper)
			.find(".layout-main-section")
			.append(
				'<div class="gateway-settings-grid">' +
					(cards ||
						'<div class="gateway-empty">' +
							__(
								"No payment gateways installed yet. Add one to start accepting payments."
							) +
							"</div>") +
					"</div>"
			);
	};

	frappe
		.call({ method: "payment_core.workspace.get_gateway_cards" })
		.then((r) => render(r.message || []));
};
