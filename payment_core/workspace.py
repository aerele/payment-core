# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Gateway navigation inside the Payment Core workspace.

The "Gateway Settings" desk page (/app/gateway-settings) is the single hub for
every installed gateway's settings — discovered from the Payment Gateway
registry at runtime, so payment_core never names a provider and the sidebar
never grows one entry per gateway.
"""

import frappe

from payment_core.analytics import get_gateways


@frappe.whitelist()
def get_gateway_cards() -> list:
	"""Cards for the Gateway Settings desk page."""
	frappe.has_permission("Payment Gateway", "read", throw=True)
	return get_gateways()


def _lookup_doctype_info(doctypes: list[str]) -> dict[str, bool]:
	"""One batched DocType query: {name: issingle} for the given candidates."""
	DocType = frappe.qb.DocType("DocType")
	rows = (
		frappe.qb.from_(DocType)
		.select(DocType.name, DocType.issingle)
		.where(DocType.name.isin(doctypes))
		.run(as_dict=True)
	)
	return {row.name: bool(row.issingle) for row in rows}


@frappe.whitelist()
def get_gateway_settings_options() -> list[dict]:
	"""Gateway types the "Add Gateway" picker may create, as [{label, route}].

	Sources, deduped and filtered to doctypes that exist on this site:
	the ``payment_gateway_settings_doctypes`` hook declared by gateway apps,
	and distinct ``gateway_settings`` values already present in the Payment
	Gateway registry. Creating a gateway account through its settings form
	is the duplicate-free path - the settings controller registers the
	properly-named Payment Gateway row on save.
	"""
	frappe.has_permission("Payment Gateway", "read", throw=True)

	candidates: list[str] = []
	for declared in frappe.get_hooks("payment_gateway_settings_doctypes") or []:
		candidates.append(declared)
	for declared in frappe.get_all("Payment Gateway", pluck="gateway_settings", distinct=True):
		if declared:
			candidates.append(declared)

	type_map = _lookup_doctype_info(candidates)

	options = []
	seen = set()
	for doctype in candidates:
		if doctype in seen or doctype not in type_map:
			continue
		seen.add(doctype)
		is_single = type_map[doctype]
		slug = frappe.desk.utils.slug(doctype)
		options.append(
			{
				"label": doctype,
				# Singles have no "new" - the form IS the settings doc
				"route": f"/app/{slug}" + ("" if is_single else "/new"),
			}
		)
	options.sort(key=lambda option: option["label"])
	return options
