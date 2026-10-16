# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Scheduled maintenance for the payment ledger."""

import datetime

import frappe
from frappe.utils import now_datetime

from payment_core.utils import (
	OPEN_TRANSACTION_STATUSES,
	_get_gateway_controller_for_transaction,
	update_payment_transaction,
)


def reconcile_stale_transactions(older_than_hours: int = 24, expire_after_days: int = 3):
	"""Re-check open transactions the webhook may have missed; expire the dead ones.

	Runs daily via scheduler_events. Each open transaction older than
	``older_than_hours`` gets one gateway re-confirm (idempotent); transactions
	still open after ``expire_after_days`` are marked Failed with a clear reason —
	provider checkout sessions cannot outlive that window.
	"""
	if not frappe.db.table_exists("Payment Transaction"):
		return
	cutoff = now_datetime() - datetime.timedelta(days=expire_after_days)
	# system context: scheduler run without a user session
	stale = frappe.get_all(
		"Payment Transaction",
		filters={"status": ("in", OPEN_TRANSACTION_STATUSES), "creation": ("<", cutoff)},
		pluck="name",
	)
	for name in stale:
		# Savepoint per row: a throwing update must not roll back the other
		# expiries in this scheduler run (same pattern as the reconcile loop)
		frappe.db.savepoint("stale_expire")
		try:
			update_payment_transaction(
				name, status="Failed", error_message="Checkout session expired without payment"
			)
		except Exception:
			frappe.db.rollback(save_point="stale_expire")
			frappe.log_error(frappe.get_traceback(), f"Stale expire failed for {name}")

	recheck_cutoff = now_datetime() - datetime.timedelta(hours=older_than_hours)
	# system context: scheduler run without a user session
	recent_open = frappe.get_all(
		"Payment Transaction",
		filters={"status": ("in", OPEN_TRANSACTION_STATUSES), "creation": ("<", recheck_cutoff)},
		pluck="name",
	)
	reconciled = 0
	for name in recent_open:
		controller = _get_gateway_controller_for_transaction(name)
		if not controller or not hasattr(controller, "reconcile_transaction"):
			continue
		# Savepoint per row: a throwing controller must not roll back the
		# expiries and reconciles already written in this scheduler run.
		frappe.db.savepoint("stale_reconcile")
		try:
			controller.reconcile_transaction(name)
			reconciled += 1
		except Exception:
			frappe.db.rollback(save_point="stale_reconcile")
			frappe.log_error(frappe.get_traceback(), f"Stale reconcile failed for {name}")
	return {"expired": len(stale), "rechecked": len(recent_open), "reconciled": reconciled}
