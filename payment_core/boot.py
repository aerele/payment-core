# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Boot-time payment policy."""

import frappe


def extend_bootinfo(bootinfo: dict) -> None:
	"""Advertise the doctypes carrying an enabled Payment Field Mapping.

	Lets the desk show the "Create Payment Transaction" action on their
	forms without an extra lookup per page.

	Sidebar suppression (hiding gateway modules' own desk sections) was
	removed: Frappe's boot sidebar payload changed between versions
	(``workspace_sidebar_item``/``default_workspace_map`` vs
	``module_sidebars``/``entity_module``), and a version-dependent boot
	hook is untestable in CI. Gateway apps that don't want their own
	workspace sidebar should not ship a workspace JSON — payment_core's
	Gateway Settings hub is the navigation surface.
	"""
	if frappe.session.user == "Guest":
		bootinfo["payment_reference_doctypes"] = []
		return

	if frappe.db.table_exists("Payment Field Mapping"):
		bootinfo["payment_reference_doctypes"] = frappe.get_all(
			"Payment Field Mapping", filters={"disabled": 0}, pluck="reference_doctype"
		)
	else:
		bootinfo["payment_reference_doctypes"] = []
