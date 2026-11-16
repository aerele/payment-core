# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT

"""Auto-create a Mode of Payment per gateway, from its Payment Gateway Accounts.

Payment Gateway Accounts are created manually from the desk (gateway +
company + payment account). ERPNext users expect each payment method to
appear as a Mode of Payment — in Payment Entries, POS, and Bank
Reconciliation — but nothing in the chain creates one. These doc_events
hooks keep one Mode of Payment per gateway (type Bank, matching the
payment account it settles into) with a company-scoped account row per
Payment Gateway Account, mirroring ERPNext's own pattern in
``Company.set_mode_of_payment_account``.
"""

import frappe

ACCOUNT_TYPES = ("Bank", "Cash", "Receivable")


def sync_for_gateway_account(doc, method=None):
	"""on_update: keep the gateway's Mode of Payment account row in sync.

	Runs on insert too (insert fires after_insert then on_update), so no
	after_insert hook is needed. Skips accounts whose type the Mode of
	Payment would reject, never overwrites a user-managed row, and returns
	early when nothing changed.
	"""
	name = doc.payment_gateway
	if not name or not doc.company or not doc.payment_account:
		return

	# Mode of Payment validates each account as an enabled, non-group
	# Bank/Cash/Receivable ledger. A PGA can hold an account that fails any
	# of those checks (an old one whose bank account was later disabled, or
	# a clearing account); the MOP save would throw, taking the PGA save —
	# or the backfill patch's migrate — down with it. Skip and log instead,
	# mirroring ERPNext's own rejection reasons.
	account = frappe.db.get_value(
		"Account", doc.payment_account, ["account_type", "is_group", "disabled"], as_dict=True
	)
	reason = None
	if not account:
		reason = "account does not exist"
	elif account.is_group:
		reason = "account is a group"
	elif account.disabled:
		reason = "account is disabled"
	elif account.account_type not in ACCOUNT_TYPES:
		reason = f"account is type {account.account_type}, not {'/'.join(ACCOUNT_TYPES)}"
	if reason:
		frappe.logger("payment_core").info(
			"mode of payment: skipping %s for gateway %s — %s: %s",
			doc.company,
			name,
			doc.payment_account,
			reason,
		)
		return

	if not frappe.db.exists("Mode of Payment", name):
		mop = frappe.get_doc(
			{
				"doctype": "Mode of Payment",
				"mode_of_payment": name,
				"type": "Bank",
				"enabled": 1,
				"accounts": [{"company": doc.company, "default_account": doc.payment_account}],
			}
		)
		mop.save(ignore_permissions=True)
		return

	mop = frappe.get_doc("Mode of Payment", name)
	row = next((r for r in mop.accounts if r.company == doc.company), None)
	if row:
		# never overwrite a user-managed row: only track the account this
		# hook itself put there (the old payment_account). The first PGA per
		# company wins; a second currency for the same company keeps the
		# original row (the MOP allows one account per company).
		old_account = _previous_payment_account(doc)
		if row.default_account == old_account and row.default_account != doc.payment_account:
			row.default_account = doc.payment_account
			mop.save(ignore_permissions=True)
		return

	mop.append("accounts", {"company": doc.company, "default_account": doc.payment_account})
	mop.save(ignore_permissions=True)


def get_gateway_mode_of_payment_name(payment_gateway):
	"""The Mode of Payment label for a Payment Gateway: its registry name.

	The gateway name is unique per gateway (``Stripe-Default``,
	``Stripe-GW-1``), so each gateway gets its own Mode of Payment. The
	gateway_controller is deliberately NOT used: gateway apps set it to the
	settings row name (e.g. ``GW-1``), which would collide across gateways.
	"""
	return frappe.db.get_value("Payment Gateway", payment_gateway, "gateway") or None


def get_mode_of_payment_for_gateway(payment_gateway):
	"""The gateway's enabled Mode of Payment name, or None.

	A disabled Mode of Payment must not be stamped onto Payment Requests:
	ERPNext's Payment Entry validate rejects disabled modes, so the buyer
	would be charged with no Payment Entry booked.
	"""
	name = get_gateway_mode_of_payment_name(payment_gateway)
	if not name:
		return None
	if frappe.db.get_value("Mode of Payment", name, "enabled"):
		return name
	return None


def _previous_payment_account(doc):
	"""The payment_account before this save, from frappe's doc_before_save."""
	before = doc.get_doc_before_save()
	return before.payment_account if before else None
