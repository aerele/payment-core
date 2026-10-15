# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

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
	is_local_route = (
		redirect_to.startswith("/")
		and not redirect_to.startswith("//")
		and not redirect_to.startswith("/\\")
		and "://" not in redirect_to
	)
	context.doctype = doctype
	context.docname = docname
	context.redirect_to = redirect_to if is_local_route else ""

	if not doctype or not docname or not frappe.db.exists(doctype, docname):
		return

	# The buyer just returned from the gateway. One immediate re-confirm
	# covers the common case — with no wait and no retries: this is a guest
	# GET, web workers must not be held busy per page load, and the page's
	# poller re-checks via reconcile_payment_status until settled anyway.
	# Settlement must not depend on a webhook or a manual desk action.
	# Web pages are GETs: flag the request so settlement writes survive it,
	# exactly like the gateway redirect handlers do.
	frappe.local.flags.commit = True
	reconcile_reference_payments(doctype, docname, retries=0, delay=0)

	doc = frappe.get_doc(doctype, docname)
	if hasattr(doc, "get_payment_success_message"):
		context.payment_message = doc.get_payment_success_message()
