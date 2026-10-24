// Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
// License: MIT. See LICENSE.

const DEFAULT_PURPOSES = [
	["amount", "Amount", ["Currency", "Float", "Int"]],
	["currency", "Currency", ["Link", "Data", "Select"]],
	["payment_method", "Payment Method", ["Select", "Data", "Link"]],
	["customer_email", "Customer Email", ["Data", "Small Text"]],
	["customer", "Customer", ["Link", "Dynamic Link"]],
	["payer_name", "Payer Name", ["Data", "Small Text"]],
	["order_id", "Order ID", ["Data", "Int", "Small Text"]],
	["due_date", "Due Date", ["Date", "Datetime"]],
	["payment_channel", "Payment Channel", ["Select", "Data"]],
	["phone_number", "Phone Number", ["Data", "Phone", "Small Text"]],
].map(([purpose, label, fieldtypes]) => ({ purpose, label, fieldtypes }));

frappe.pages["payment-field-mapping-builder"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Payment Field Mapping"),
		single_column: true,
	});
};

frappe.pages["payment-field-mapping-builder"].on_page_show = function (wrapper) {
	load_payment_field_mapping_builder(wrapper);
};

async function load_payment_field_mapping_builder(wrapper) {
	const parent = $(wrapper).find(".layout-main-section");
	const route_options = frappe.route_options || {};
	const reference_doctype = route_options.reference_doctype || route_options.doctype || "";

	wrapper.payment_field_mapping_builder?.destroy?.();
	parent.empty();

	try {
		await frappe.require("payment_field_mapping_builder.bundle.js");
		wrapper.payment_field_mapping_builder =
			new window.payment_core.ui.PaymentFieldMappingVisualBuilder({
				wrapper: parent,
				page: wrapper.page,
				reference_doctype,
			});
	} catch (error) {
		console.error(error);
		frappe.msgprint({
			title: __("Visual builder unavailable"),
			message: __("The standard field mapper has been opened instead."),
			indicator: "orange",
		});
		wrapper.payment_field_mapping_builder = new PaymentFieldMappingBuilder(wrapper.page);
	}
}

class PaymentFieldMappingBuilder {
	constructor(page) {
		this.page = page;
		this.data = null;
		this.request_id = 0;
		this.dirty = false;
		this.render_shell();
		this.setup_controls();
		this.setup_toolbar();
		this.load_from_route();
	}

	setup_controls() {
		this.doctype_control = frappe.ui.form.make_control({
			parent: this.page.body.find(".reference-doctype-control"),
			df: {
				label: __("Reference DocType"),
				fieldname: "reference_doctype",
				fieldtype: "Link",
				options: "DocType",
				get_query: () => ({ filters: { istable: 0, issingle: 0 } }),
				change: () => this.load_mapping(this.doctype_control.get_value()),
			},
			render_input: true,
		});
		this.disabled_control = frappe.ui.form.make_control({
			parent: this.page.body.find(".payment-mapping-disabled-control"),
			df: {
				label: __("Disabled"),
				fieldname: "disabled",
				fieldtype: "Check",
				change: () => {
					this.dirty = true;
				},
			},
			render_input: true,
		});
	}

	setup_toolbar() {
		this.page.set_primary_action(__("Save Mapping"), () => this.save_mapping());
		this.page.add_menu_item(__("Open Stored Mappings"), () =>
			frappe.set_route("List", "Payment Field Mapping")
		);
	}

	render_shell() {
		$(this.page.body).html(`
			<div class="payment-field-mapping-builder-page">
				<div class="payment-mapping-intro">
					<div class="mapping-icon">${frappe.utils.icon("map", "md")}</div>
					<div>
						<h3>${__("Map payment purposes to reference fields")}</h3>
						<p>${__("Choose the fields payment_core should read when creating a payment.")}</p>
					</div>
				</div>
				<div class="payment-mapping-config">
					<div class="reference-doctype-control"></div>
					<div class="payment-mapping-disabled-control"></div>
				</div>
				<div class="payment-mapping-canvas">
					<div class="payment-mapping-canvas-header">
						<span>${__("Payment purpose")}</span>
						<span class="mapping-field-heading">${__("Reference field")}</span>
					</div>
					<div class="payment-mapping-rows"></div>
					<div class="payment-mapping-footer">
						<span class="amount-note">${__("Amount is required")}</span>
						<span class="mapping-status"></span>
					</div>
				</div>
			</div>
		`);
		this.render_rows(DEFAULT_PURPOSES, [], []);
	}

	load_from_route() {
		const route_options = frappe.route_options || {};
		const doctype = route_options.reference_doctype || route_options.doctype;
		if (doctype) {
			this.doctype_control.set_input(doctype);
			this.load_mapping(doctype);
		} else {
			this.load_mapping("");
		}
	}

	load_mapping(doctype) {
		const request_id = ++this.request_id;
		if (!doctype) {
			this.data = null;
			this.dirty = false;
			this.disabled_control.set_input(false);
			this.render_rows(DEFAULT_PURPOSES, [], []);
			this.set_status(__("Select a reference DocType"), "orange");
			return;
		}

		this.data = null;
		this.set_loading(true);
		frappe
			.xcall("payment_core.field_mapping.get_mapping_builder_data", { doctype })
			.then((data) => {
				if (request_id !== this.request_id) return;
				this.data = data;
				this.disabled_control.set_input(Boolean(data.disabled));
				this.dirty = false;
				this.render_rows(
					data.purposes || DEFAULT_PURPOSES,
					data.mapping || [],
					data.fields || []
				);
				this.set_status(
					data.mapping_name ? __("Stored mapping loaded") : __("Not configured yet"),
					data.mapping_name ? "green" : "orange"
				);
			})
			.finally(() => {
				if (request_id === this.request_id) this.set_loading(false);
			});
	}

	render_rows(purposes, mapping, fields) {
		const mappings = Object.fromEntries(
			mapping.map((row) => [row.purpose, row.reference_field])
		);
		const field_by_name = Object.fromEntries(fields.map((field) => [field.fieldname, field]));
		const html = purposes
			.map((purpose) => {
				const current = mappings[purpose.purpose] || "";
				const choices = fields.filter((field) =>
					purpose.fieldtypes.includes(field.fieldtype)
				);
				if (current && !field_by_name[current]) {
					choices.push({ fieldname: current, fieldtype: __("Stored field") });
				}
				const options = [
					`<option value="">${__("Not mapped")}</option>`,
					...choices.map(
						(field) =>
							`<option value="${frappe.utils.escape_html(field.fieldname)}" ${
								field.fieldname === current ? "selected" : ""
							}>${frappe.utils.escape_html(field.label || field.fieldname)}</option>`
					),
				].join("");
				const required = purpose.purpose === "amount";
				return `
					<div class="payment-mapping-row ${required ? "is-required" : ""}" data-purpose="${
					purpose.purpose
				}">
						<div class="payment-purpose-card">
							<span class="payment-purpose-dot"></span>
							<div>
								<span class="payment-purpose-name">${frappe.utils.escape_html(__(purpose.label))}</span>
								<span class="payment-purpose-key">${frappe.utils.escape_html(purpose.purpose)}${
					required ? ` · ${__("required")}` : ""
				}</span>
							</div>
						</div>
						<div class="payment-mapping-connector">→</div>
						<div class="payment-mapping-field">
							<select data-purpose="${purpose.purpose}" ${
					this.data ? "" : "disabled"
				} aria-label="${frappe.utils.escape_html(
					__(purpose.label) + " " + __("reference field")
				)}">${options}</select>
						</div>
					</div>
				`;
			})
			.join("");

		this.page.body.find(".payment-mapping-rows").html(html);
		this.page.body.find(".payment-mapping-rows select").on("change", () => {
			this.dirty = true;
			this.set_status(__("Unsaved changes"), "orange");
		});
	}

	collect_mapping() {
		return this.page.body
			.find(".payment-mapping-rows select")
			.map(function () {
				return { purpose: $(this).data("purpose"), reference_field: $(this).val() };
			})
			.get()
			.filter((row) => row.reference_field);
	}

	save_mapping() {
		const reference_doctype = this.doctype_control.get_value();
		if (!reference_doctype) {
			frappe.throw(__("Select a reference DocType first."));
		}
		const mapping = this.collect_mapping();
		if (!mapping.some((row) => row.purpose === "amount")) {
			frappe.throw(__("Select a reference field for Amount."));
		}

		this.set_loading(true);
		frappe
			.xcall("payment_core.field_mapping.save_mapping_builder_data", {
				reference_doctype,
				mapping,
				disabled: this.disabled_control.get_value() ? 1 : 0,
			})
			.then((result) => {
				this.dirty = false;
				this.data = this.data || {};
				this.data.mapping_name = result.name;
				this.data.disabled = result.disabled;
				this.set_status(__("Mapping saved"), "green");
				frappe.show_alert({
					message: __("Payment field mapping saved"),
					indicator: "green",
				});
			})
			.finally(() => this.set_loading(false));
	}

	set_status(message, color) {
		this.page.body
			.find(".mapping-status")
			.html(
				`<span class="indicator-pill ${color}">${frappe.utils.escape_html(message)}</span>`
			);
		this.page.set_indicator(message, color);
	}

	set_loading(loading) {
		this.page.btn_primary.prop("disabled", loading);
		this.page.body
			.find(".payment-mapping-rows select")
			.prop("disabled", loading || !this.data);
	}
}
