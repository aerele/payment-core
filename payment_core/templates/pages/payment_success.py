# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import frappe

no_cache = True


def get_context(context):
	context.payment_message = ""

	doctype = frappe.local.form_dict.get("doctype")
	docname = frappe.local.form_dict.get("docname")
	if not doctype or not docname or not frappe.db.exists(doctype, docname):
		return

	doc = frappe.get_doc(doctype, docname)
	if hasattr(doc, "get_payment_success_message"):
		context.payment_message = doc.get_payment_success_message()
