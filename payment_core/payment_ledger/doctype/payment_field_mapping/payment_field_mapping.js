// Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
// License: MIT. See LICENSE

// Fieldtypes on the reference doctype that can serve each payment purpose.
// Purely a picker hint: the server validates existence, not type.
const PURPOSE_FIELD_TYPES = {
	amount: ["Currency", "Float", "Int"],
	currency: ["Link", "Data", "Select"],
	payment_method: ["Select", "Data", "Link"],
	customer_email: ["Data", "Small Text"],
	customer: ["Link", "Dynamic Link"],
	payer_name: ["Data", "Small Text"],
	order_id: ["Data", "Int", "Small Text"],
	due_date: ["Date", "Datetime"],
	payment_channel: ["Select", "Data"],
	phone_number: ["Data", "Phone", "Small Text"],
};

frappe.ui.form.on("Payment Field Mapping", {
	refresh(frm) {
		load_mappable_fields(frm);
	},
	reference_doctype(frm) {
		// Field names from a previous doctype no longer apply.
		frm.doc.mapping = [];
		refresh_field("mapping");
		load_mappable_fields(frm);
	},
});

frappe.ui.form.on("Payment Field Mapping Item", {
	purpose(frm, cdt, cdn) {
		// Re-suggest fields compatible with the newly chosen purpose.
		const row = locals[cdt][cdn];
		const grid_row = frm.fields_dict.mapping.grid.grid_rows_by_docname[cdn];
		if (grid_row && grid_row.grid_form) {
			apply_field_options(grid_row.grid_form.fields_dict.reference_field, row.purpose, frm);
		}
	},
	form_render(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const grid_row = frm.fields_dict.mapping.grid.grid_rows_by_docname[cdn];
		if (grid_row && grid_row.grid_form) {
			apply_field_options(grid_row.grid_form.fields_dict.reference_field, row.purpose, frm);
		}
	},
});

function load_mappable_fields(frm) {
	if (!frm.doc.reference_doctype) {
		frm._mappable_fields = null;
		return;
	}
	frappe
		.xcall("payment_core.utils.get_mappable_fields", { doctype: frm.doc.reference_doctype })
		.then((fields) => {
			frm._mappable_fields = fields;
			// Rows already rendered before the fetch landed need their pickers fed.
			(frm.doc.mapping || []).forEach((row) => {
				const grid_row = frm.fields_dict.mapping.grid.grid_rows_by_docname[row.name];
				if (grid_row && grid_row.grid_form) {
					apply_field_options(
						grid_row.grid_form.fields_dict.reference_field,
						row.purpose,
						frm
					);
				}
			});
		});
}

function apply_field_options(control, purpose, frm) {
	if (!control) {
		return;
	}
	const fields = frm._mappable_fields || [];
	const allowed_types = PURPOSE_FIELD_TYPES[purpose] || [];
	const options = fields
		.filter((field) => allowed_types.includes(field.fieldtype))
		.map((field) => field.fieldname);
	// keep a stored value visible even when its type no longer matches
	if (control.value && !options.includes(control.value)) {
		options.push(control.value);
	}
	control.df.options = options;
	// Autocomplete only reads df.options at control creation;
	// feed its suggestion engine directly too.
	if (control.set_data) {
		control.set_data(options);
	}
}
