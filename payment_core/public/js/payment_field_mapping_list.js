// Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
// License: MIT. See LICENSE

frappe.listview_settings["Payment Field Mapping"] = {
	add_fields: ["disabled", "reference_doctype"],
	get_indicator(doc) {
		if (doc.disabled) {
			return [__("Disabled"), "gray", "disabled,=,1"];
		}
		return [__("Enabled"), "green", "disabled,=,0"];
	},
	button: {
		show(doc) {
			return doc.name;
		},
		get_label() {
			return frappe.utils.icon("edit", "sm");
		},
		get_description(doc) {
			return __("Map {0}", [`${doc.reference_doctype}`]);
		},
		action(doc) {
			frappe.route_options = { reference_doctype: doc.reference_doctype };
			frappe.set_route("payment-field-mapping-builder");
		},
	},
};
