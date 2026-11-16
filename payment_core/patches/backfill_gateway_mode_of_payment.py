# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT

import frappe


def execute():
	"""Backfill: create the gateway's Mode of Payment for existing PGAs.

	Sites that already have Payment Gateway Accounts get nothing from the
	doc_events hook until someone re-saves them. This patch runs the same
	sync for each existing account, so the MOP is present from the first
	migrate after upgrading. The sync itself skips accounts the Mode of
	Payment would reject.

	One bad account (say, a bank account disabled years after the PGA was
	created) must not stop the whole migrate: each account runs inside its
	own savepoint, failures roll back, land in Error Log and the patch
	moves on.
	"""
	if not frappe.db.exists("DocType", "Payment Gateway Account"):
		return

	from payment_core.mode_of_payment import sync_for_gateway_account

	for name in frappe.get_all("Payment Gateway Account", pluck="name"):
		doc = frappe.get_doc("Payment Gateway Account", name)
		savepoint = f"mop_backfill_{frappe.generate_hash(length=8)}"
		frappe.db.savepoint(savepoint)
		try:
			sync_for_gateway_account(doc, method="on_update")
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			frappe.clear_last_message()
			# logged after the rollback so the Error Log row itself survives
			frappe.log_error(
				title="Mode of Payment backfill failed",
				message=f"Payment Gateway Account {name}: gateway {doc.payment_gateway}, company {doc.company}, account {doc.payment_account}",
				reference_doctype="Payment Gateway Account",
				reference_name=name,
			)
