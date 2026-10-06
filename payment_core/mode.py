# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Site-level payment mode: full ledger vs gateway-only.

Apps that own their payment flow — ERPNext (Payment Request / Payment Entry),
LMS-style apps, or any custom app with its own payment doctypes — declare it
in their hooks (``uses_own_payment_flow = True``). On such sites payment_core
runs as the gateway layer only: their documents are the payment references
and the shared ledger doctypes are never installed (see ledger_gate).
"""

import frappe

# doctypes that exist only in full-ledger mode
LEDGER_DOCTYPES = (
	"Payment Transaction",
	"Payment Receipt",
	"Payment Field Mapping",
	"Payment Field Mapping Item",
)

# the module carrying them; suppressed from schema sync in gateway-only mode
LEDGER_MODULE = "Payment Ledger"

# ledger-only desk artifacts removed in gateway-only mode
LEDGER_PAGE = "payment-field-mapping-builder"
LEDGER_REPORT = "Payment Settlement Summary"

# workspace items that only make sense with the ledger installed
LEDGER_SIDEBAR_LABELS = ("Payment Transaction", "Payment Receipt", "Field Mapping")
LEDGER_SHORTCUT_LABELS = ("Payment Transaction", "Payment Receipt")


def is_gateway_only() -> bool:
	"""Whether payment_core runs without the shared ledger on this site.

	True when ERPNext is installed (its Payment Request / Payment Entry flow
	is the reference), when any installed app declares ``uses_own_payment_flow``
	, or — the escape hatch — unless ``force_payment_ledger`` is set in site
	config to keep the ledger regardless.
	"""
	if frappe.conf.force_payment_ledger:
		return False
	if "erpnext" in frappe.get_installed_apps():
		return True
	return bool(frappe.get_hooks("uses_own_payment_flow"))


def gateway_only_reason() -> str | None:
	"""Human-readable explanation of the active mode, for logs and setup notes."""
	if frappe.conf.force_payment_ledger:
		return None
	if "erpnext" in frappe.get_installed_apps():
		return "ERPNext is installed (Payment Request / Payment Entry is the payment flow)"
	owners = frappe.get_hooks("uses_own_payment_flow") or []
	if owners:
		apps = sorted({str(owner).split(".", 1)[0] for owner in owners})
		return "App with its own payment flow installed: " + ", ".join(apps)
	return None


def ledger_installed() -> bool:
	"""Whether the ledger doctypes exist on this site."""
	return bool(frappe.db.table_exists("Payment Transaction"))
