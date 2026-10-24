# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from urllib.parse import unquote

import frappe

from payment_core.utils import reconcile_reference_payments

no_cache = True


def get_context(context):
	context.payment_message = ""

	doctype = frappe.local.form_dict.get("doctype") or ""
	docname = frappe.local.form_dict.get("docname") or ""
	redirect_to = frappe.local.form_dict.get("redirect_to") or ""
	# The success page is guest-reachable, so its query string is attacker
	# input: only same-origin routes may become the buyer's redirect target.
	# Browsers strip control characters (raw or %XX-encoded, e.g. /%09/) and
	# can then read a "local" path as scheme-relative - so validate the
	# decoded form too, not just the raw string.
	decoded_redirect = unquote(redirect_to)
	is_local_route = all(
		candidate.startswith("/")
		and not candidate.startswith("//")
		and not candidate.startswith("/\\")
		and ":" not in candidate
		and not any(ord(ch) < 32 or ch.isspace() for ch in candidate)
		for candidate in (redirect_to, decoded_redirect)
	)
	context.doctype = doctype
	context.docname = docname
	context.redirect_to = redirect_to if is_local_route else ""

	if not doctype or not docname or not frappe.db.exists(doctype, docname):
		return

	# One immediate re-confirm with no wait/retries (guest GET; the page
	# poller keeps re-checking). GETs need the commit flag so settlement
	# writes survive, like the gateway redirect handlers.
	frappe.local.flags.commit = True
	reconcile_reference_payments(doctype, docname, retries=0, delay=0)

	doc = frappe.get_doc(doctype, docname)
	if hasattr(doc, "get_payment_success_message"):
		context.payment_message = doc.get_payment_success_message()
