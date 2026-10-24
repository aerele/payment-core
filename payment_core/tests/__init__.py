import frappe
from frappe.defaults import set_global_default


def before_tests() -> None:
	"""Supply the minimum site default required by payment integration tests."""
	if frappe.db.get_single_value("System Settings", "currency"):
		return

	frappe.db.set_single_value("System Settings", "currency", "USD")
	set_global_default("currency", "USD")
	frappe.db.commit()
	frappe.clear_cache(doctype="System Settings")
