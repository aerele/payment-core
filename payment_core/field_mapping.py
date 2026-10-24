# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Guards for Payment Field Mapping lifecycle."""

import frappe
from frappe import _
from frappe.utils import cint

from payment_core.utils import PAYMENT_REFERENCE_PURPOSES, get_mappable_fields

PURPOSE_FIELD_TYPES = {
	"amount": ["Currency", "Float", "Int"],
	"currency": ["Link", "Data", "Select"],
	"payment_method": ["Select", "Data", "Link"],
	"customer_email": ["Data", "Small Text"],
	"customer": ["Link", "Dynamic Link"],
	"payer_name": ["Data", "Small Text"],
	"order_id": ["Data", "Int", "Small Text"],
	"due_date": ["Date", "Datetime"],
	"payment_channel": ["Select", "Data"],
	"phone_number": ["Data", "Phone", "Small Text"],
}


def on_custom_field_trash(doc, method=None):
	"""Block deletion of a Custom Field a Payment Field Mapping still references.

	Without this, deleting the field would silently push the mapping onto the
	built-in fallback candidates.
	"""
	if not doc.dt or not doc.fieldname:
		return
	if not frappe.db.table_exists("Payment Field Mapping"):
		return
	mappings = frappe.get_all(
		"Payment Field Mapping",
		filters={"reference_doctype": doc.dt},
		pluck="name",
	)
	if not mappings:
		return
	rows = frappe.get_all(
		"Payment Field Mapping Item",
		filters={
			"parenttype": "Payment Field Mapping",
			"parent": ("in", mappings),
			"reference_field": doc.fieldname,
		},
		fields=["parent", "purpose"],
	)
	for row in rows:
		frappe.throw(
			_("{0} is mapped as the {1} on {2}. Update that mapping before deleting this field.").format(
				frappe.bold(doc.fieldname),
				frappe.bold(frappe.unscrub(row.purpose)),
				frappe.bold(row.parent),
			)
		)


def _get_builder_purposes() -> list[dict]:
	return [
		{
			"purpose": purpose,
			"label": _(frappe.unscrub(purpose)),
			"fieldtypes": PURPOSE_FIELD_TYPES.get(purpose, []),
		}
		for purpose in PAYMENT_REFERENCE_PURPOSES
	]


@frappe.whitelist()
def get_mapping_builder_data(doctype: str) -> dict:
	"""Return the field choices and stored mapping for the visual mapper."""
	frappe.has_permission("Payment Field Mapping", "read", throw=True)
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("DocType {0} does not exist").format(doctype))
	frappe.has_permission(doctype, "read", throw=True)

	if not frappe.db.table_exists("Payment Field Mapping"):
		frappe.throw(_("Payment Field Mapping is not installed on this site"))
	# the builder edits the enabled mapping first; a disabled one only opens
	# when no enabled mapping exists for the doctype
	mapping_rows = frappe.get_all(
		"Payment Field Mapping",
		filters={"reference_doctype": doctype, "disabled": 0},
		fields=["name", "disabled"],
		order_by="modified desc",
		limit=1,
	)
	if not mapping_rows:
		mapping_rows = frappe.get_all(
			"Payment Field Mapping",
			filters={"reference_doctype": doctype},
			fields=["name", "disabled"],
			order_by="modified desc",
			limit=1,
		)
	stored_mapping = mapping_rows[0] if mapping_rows else None
	rows = []
	if stored_mapping:
		rows = frappe.get_all(
			"Payment Field Mapping Item",
			filters={
				"parenttype": "Payment Field Mapping",
				"parent": stored_mapping.name,
				"parentfield": "mapping",
			},
			fields=["purpose", "reference_field"],
			order_by="idx asc",
		)

	return {
		"reference_doctype": doctype,
		"mapping_name": stored_mapping.name if stored_mapping else None,
		"disabled": bool(cint(stored_mapping.disabled)) if stored_mapping else False,
		"purposes": _get_builder_purposes(),
		"fields": get_mappable_fields(doctype),
		"mapping": rows,
	}


@frappe.whitelist(methods=["POST"])
def save_mapping_builder_data(
	reference_doctype: str, mapping: str | list[dict], disabled: bool = False
) -> dict:
	"""Validate and persist the visual mapper into Payment Field Mapping."""
	if not frappe.db.exists("DocType", reference_doctype):
		frappe.throw(_("DocType {0} does not exist").format(reference_doctype))
	frappe.has_permission(reference_doctype, "read", throw=True)

	# update the enabled mapping when one exists; when the doctype only has
	# a disabled mapping, the builder just opened that one - update it too
	# (saving enables it) instead of creating a second mapping
	existing = frappe.get_all(
		"Payment Field Mapping",
		filters={"reference_doctype": reference_doctype, "disabled": 0},
		fields=["name"],
		order_by="modified desc",
		limit=1,
	)
	if not existing:
		existing = frappe.get_all(
			"Payment Field Mapping",
			filters={"reference_doctype": reference_doctype},
			fields=["name"],
			order_by="modified desc",
			limit=1,
		)
	frappe.has_permission("Payment Field Mapping", "write" if existing else "create", throw=True)

	if isinstance(mapping, str):
		mapping = frappe.parse_json(mapping)
	if not isinstance(mapping, list):
		frappe.throw(_("Mapping data must be a list of payment purposes and fields."))

	rows = []
	seen_purposes = set()
	valid_purposes = set(PAYMENT_REFERENCE_PURPOSES)
	for row in mapping:
		if not isinstance(row, dict):
			frappe.throw(_("Each payment mapping must be an object."))
		purpose = str(row.get("purpose") or "").strip()
		reference_field = str(row.get("reference_field") or "").strip()
		if not purpose and not reference_field:
			continue
		if purpose not in valid_purposes:
			frappe.throw(_("Unknown payment purpose {0}").format(frappe.bold(purpose)))
		if not reference_field:
			frappe.throw(
				_("Select a reference field for {0}.").format(frappe.bold(_(frappe.unscrub(purpose))))
			)
		if purpose in seen_purposes:
			frappe.throw(_("Purpose {0} is mapped more than once").format(frappe.bold(purpose)))
		seen_purposes.add(purpose)
		rows.append({"purpose": purpose, "reference_field": reference_field})

	if "amount" not in seen_purposes:
		frappe.throw(_("An amount mapping is required"))

	if existing:
		doc = frappe.get_doc("Payment Field Mapping", existing[0].name)
		doc.set("mapping", [])
		for row in rows:
			doc.append("mapping", row)
		doc.disabled = cint(disabled)
		doc.save()
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Payment Field Mapping",
				"reference_doctype": reference_doctype,
				"disabled": cint(disabled),
				"mapping": rows,
			}
		).insert()

	return {
		"name": doc.name,
		"disabled": bool(doc.disabled),
		"mapping": [{"purpose": row.purpose, "reference_field": row.reference_field} for row in doc.mapping],
	}
