# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Shared, gateway-agnostic helpers used across the payment gateway logic.

from contextlib import contextmanager

import frappe
from frappe import _


def validate_integration_request(docname: str | None):
	if frappe.db.get_value("Integration Request", docname, "status") == "Cancelled":
		frappe.throw(_("Expired Token"))


def get_payment_gateway_controller(payment_gateway):
	"""Return payment gateway controller"""
	gateway = frappe.get_doc("Payment Gateway", payment_gateway)
	if gateway.gateway_controller is None:
		try:
			return frappe.get_doc(f"{payment_gateway} Settings")
		except Exception:
			frappe.throw(_("{0} Settings not found").format(payment_gateway))
	else:
		try:
			return frappe.get_doc(gateway.gateway_settings, gateway.gateway_controller)
		except Exception:
			frappe.throw(_("{0} Settings not found").format(payment_gateway))


# nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
@frappe.whitelist(allow_guest=True, xss_safe=True)
def get_checkout_url(**kwargs):
	try:
		if kwargs.get("payment_gateway"):
			doc = frappe.get_doc("{} Settings".format(kwargs.get("payment_gateway")))
			return doc.get_payment_url(**kwargs)
		else:
			raise Exception
	except Exception:
		frappe.respond_as_web_page(
			_("Something went wrong"),
			_(
				"Looks like something is wrong with this site's payment gateway configuration. No payment has been made."
			),
			indicator_color="red",
			http_status_code=frappe.ValidationError.http_status_code,
		)


def create_payment_gateway(gateway, settings=None, controller=None):
	# NOTE: we don't translate Payment Gateway name because it is an internal doctype
	if not frappe.db.exists("Payment Gateway", gateway):
		payment_gateway = frappe.get_doc(
			{
				"doctype": "Payment Gateway",
				"gateway": gateway,
				"gateway_settings": settings,
				"gateway_controller": controller,
			}
		)
		payment_gateway.insert(ignore_permissions=True)


def before_install():
	# Guard used during ERPNext CI patch tests (v10 restore path lacks Module Def.custom).
	if not frappe.get_meta("Module Def").has_field("custom"):
		return False


def is_v2_gateway(payment_gateway=None):
	"""Whether the gateway uses the V2 PaymentController contract.

	Gateways here implement the legacy V1 contract, so this is always False and
	ERPNext keeps its V1 flow. Exists so ERPNext can import it from payment_core.
	"""
	return False


@contextmanager
def erpnext_app_import_guard():
	marketplace_link = '<a href="https://frappecloud.com/marketplace/apps/erpnext">Marketplace</a>'
	github_link = '<a href="https://github.com/frappe/erpnext">GitHub</a>'
	msg = _("erpnext app is not installed. Please install it from {} or {}").format(
		marketplace_link, github_link
	)
	try:
		yield
	except ImportError:
		frappe.throw(msg, title=_("Missing ERPNext App"))


def guard_payment_reference(reference_doctype, reference_docname):
	"""Reject payment endpoints pointed at an arbitrary or non-existent reference.

	The reference must be a real document. Authenticated callers must also have
	read access; guests legitimately cannot (Payment Request grants no Guest
	permission), so for them the existence check is the guard.
	"""
	if not (
		reference_doctype and reference_docname and frappe.db.exists(reference_doctype, reference_docname)
	):
		frappe.throw(_("Invalid payment reference."), frappe.PermissionError)
	if frappe.session.user != "Guest":
		frappe.has_permission(reference_doctype, "read", reference_docname, throw=True)


def get_reference_amount(reference_doctype, reference_docname):
	"""Authoritative payable amount + currency, read server-side from the reference.

	Never trust a client-supplied amount: without this an attacker can post any
	value (e.g. 0.01) and settle a full order for a token amount. Raises when the
	reference carries no amount field.
	"""
	meta = frappe.get_meta(reference_doctype)
	amount_field = "grand_total" if meta.has_field("grand_total") else "amount"
	if not meta.has_field(amount_field):
		frappe.throw(_("Cannot determine the payable amount for {0}.").format(reference_doctype))
	fields = [amount_field] + (["currency"] if meta.has_field("currency") else [])
	row = frappe.db.get_value(reference_doctype, reference_docname, fields, as_dict=True)
	if not row:
		frappe.throw(_("Payment reference {0} no longer exists.").format(reference_docname))
	return row.get(amount_field), row.get("currency")
