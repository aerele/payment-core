# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model import default_fields
from frappe.model.document import Document

from payment_core.utils import PAYMENT_REFERENCE_PURPOSES

# fields that can never carry a resolvable payment value
UNMAPPABLE_FIELDTYPES = {
	"Table",
	"Table MultiSelect",
	"Attach",
	"Attach Image",
	"Image",
	"HTML",
	"Button",
	"Heading",
	"Section Break",
	"Column Break",
	"Tab Break",
}


class PaymentFieldMapping(Document):
	"""Declares which fields of a reference doctype serve each payment purpose."""

	def validate(self):
		if not frappe.db.exists("DocType", self.reference_doctype):
			frappe.throw(_("DocType {0} does not exist").format(self.reference_doctype))
		self.validate_mapped_fields()
		self.validate_unique_per_doctype()

	def validate_mapped_fields(self):
		meta = frappe.get_meta(self.reference_doctype)
		seen_purposes = set()
		for row in self.mapping:
			if row.purpose not in PAYMENT_REFERENCE_PURPOSES:
				frappe.throw(_("Unknown payment purpose {0}").format(frappe.bold(row.purpose)))
			if row.purpose in seen_purposes:
				frappe.throw(_("Purpose {0} is mapped more than once").format(frappe.bold(row.purpose)))
			seen_purposes.add(row.purpose)
			fieldname = (row.reference_field or "").strip()
			row.reference_field = fieldname
			# default_fields (owner, modified_by, ...) are not DocFields but
			# are valid, useful mapping targets.
			if fieldname and not (meta.has_field(fieldname) or fieldname in default_fields):
				frappe.throw(
					_("{0} does not exist on {1}").format(frappe.bold(fieldname), self.reference_doctype)
				)
			# server-side fieldtype check: structural/binary fieldtypes can
			# never resolve to a payment value. Amount stays open to any
			# data-ish field on purpose - values pass through flt() at
			# resolution, and string amount fields are a supported case.
			field_meta = meta.get_field(fieldname) if fieldname else None
			if field_meta and field_meta.fieldtype in UNMAPPABLE_FIELDTYPES:
				frappe.throw(
					_("{0} ({1}) cannot serve payment purpose {2}").format(
						frappe.bold(fieldname), field_meta.fieldtype, frappe.bold(row.purpose)
					)
				)
		if "amount" not in seen_purposes:
			frappe.throw(_("An amount mapping is required"))

	def validate_unique_per_doctype(self):
		if self.disabled:
			return
		filters = {"reference_doctype": self.reference_doctype, "disabled": 0}
		if self.name:
			filters["name"] = ("!=", self.name)
		if frappe.db.exists("Payment Field Mapping", filters):
			frappe.throw(_("An enabled mapping for {0} already exists").format(self.reference_doctype))
