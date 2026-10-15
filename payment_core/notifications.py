# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Generic ledger notifications: tell Payment Managers when money goes wrong."""

import frappe
from frappe import _
from frappe.utils import fmt_money

WATCHED_STATUSES = ("Failed", "Partially Paid")


def on_transaction_update(doc, method=None):
	"""Alert Payment Managers on first transition into a watched status."""
	if doc.status not in WATCHED_STATUSES:
		return
	previous = doc.get_doc_before_save()
	if previous and previous.status == doc.status:
		return  # already announced; avoids repeat alerts on routine saves
	recipients = get_payment_manager_emails()
	if not recipients:
		return
	subject = _("Payment {0}: {1}").format(doc.name, doc.status)
	message = _("Payment Transaction {0} for {1} {2} is now {3} ({4}).").format(
		frappe.bold(doc.name),
		frappe.utils.escape_html(doc.reference_doctype or ""),
		frappe.bold(frappe.utils.escape_html(doc.reference_docname or "")),
		frappe.bold(doc.status),
		fmt_money(doc.amount, currency=doc.currency),
	)
	if doc.status == "Failed" and doc.error_message:
		reason_label = _("Reason:")
		message += "<br><br>" + frappe.bold(reason_label) + " " + frappe.utils.escape_html(doc.error_message)
	url = frappe.utils.get_url_to_form("Payment Transaction", doc.name)
	try:
		frappe.sendmail(
			recipients=recipients,
			subject=subject,
			message=f'<p style="font-family: sans-serif">{message}</p><p><a href="{url}">{url}</a></p>',
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Payment status alert failed")


def get_payment_manager_emails():
	"""Emails of active Payment Managers, in one joined query."""
	# system context: alert path may run from scheduler-settled transactions
	HasRole = frappe.qb.DocType("Has Role")
	User = frappe.qb.DocType("User")
	query = (
		frappe.qb.from_(HasRole)
		.join(User)
		.on(User.name == HasRole.parent)
		.select(User.email)
		.where(
			(HasRole.role == "Payment Manager")
			& (HasRole.parenttype == "User")
			& (User.enabled == 1)
			& User.email.notnull()
		)
		.distinct()
	)
	return [row[0] for row in query.run(as_list=True)]
