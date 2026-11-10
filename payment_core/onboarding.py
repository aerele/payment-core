# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT

"""Keep the "Get payments ready" onboarding steps reflecting real site state.

"Go to Page" steps tick themselves when clicked (frappe's own widget
behavior), so a step could show done before the work is. The sync below is
the source of truth: it runs on migrate and on every analytics load, setting
each step's completion from what the site actually has. A premature click
self-heals on the next dashboard render.
"""

import frappe

from payment_core.analytics_display import load_gateway_controllers

WEBHOOK_STEP = "Set the Webhook Signing Secret"
GATEWAY_STEP = "Connect a Payment Gateway"
TEST_PAYMENT_STEP = "Take a Test Payment"


def sync_onboarding_steps(controllers=None):
	"""Converge the payment onboarding steps to the site's real state."""
	if not frappe.db.exists("DocType", "Onboarding Step"):
		return
	if controllers is None:
		controllers = load_gateway_controllers()

	resolved = [(row, controller) for row, controller in controllers if controller is not None]
	_set_step_complete(GATEWAY_STEP, bool(resolved))
	_set_step_complete(WEBHOOK_STEP, _gateways_report_clean_webhooks(resolved))
	_set_step_complete(TEST_PAYMENT_STEP, _has_a_captured_payment())


def _gateways_report_clean_webhooks(resolved):
	"""True when at least one gateway is installed and every controller that
	exposes the structured ``is_webhook_configured`` signal reports it
	configured. Health-warning text is translated and must never be matched.
	Controllers without the signal neither block nor satisfy the step: when
	no gateway reports it, the step stays undone rather than assuming
	configuration."""
	if not resolved:
		return False
	signalling = [controller for _row, controller in resolved if hasattr(controller, "is_webhook_configured")]
	if not signalling:
		return False
	return all(controller.is_webhook_configured() for controller in signalling)


def _has_a_captured_payment():
	"""Mode-aware: a submitted capture receipt on ledger sites; on gateway-only
	(ERPNext) sites a submitted Payment Entry that settles a Payment Request
	(settlement stamps the request name as reference_no) - a hand-made cash or
	bank entry must not tick the step. exists(), never count: this runs on
	every analytics load."""
	if frappe.db.table_exists("Payment Receipt"):
		return bool(frappe.db.exists("Payment Receipt", {"docstatus": 1, "entry_type": "Capture"}))
	if frappe.db.table_exists("Payment Entry"):
		return _gateway_payment_entry_exists()
	return False


def _gateway_payment_entry_exists():
	"""A submitted Payment Entry that settles a Payment Request carrying a
	payment gateway. ERPNext also stamps reference_no with the request name
	for a hand-made entry (e.g. a bank transfer recorded from the request):
	only gateway-backed requests count as gateway payments. One joined,
	first-row-stopping query - a name list would grow with every request on
	a busy site."""
	if not frappe.db.table_exists("Payment Request"):
		return False
	PaymentEntry = frappe.qb.DocType("Payment Entry")
	PaymentRequest = frappe.qb.DocType("Payment Request")
	return bool(
		(
			frappe.qb.from_(PaymentEntry)
			.inner_join(PaymentRequest)
			.on(PaymentEntry.reference_no == PaymentRequest.name)
			.select(PaymentRequest.name)
			.where(PaymentEntry.docstatus == 1)
			.where(PaymentRequest.payment_gateway.notnull())
			.where(PaymentRequest.payment_gateway != "")
			.limit(1)
		).run()
	)


def _set_step_complete(step, done):
	if not frappe.db.exists("Onboarding Step", step):
		return
	current = frappe.db.get_value("Onboarding Step", step, "is_complete")
	if bool(frappe.utils.cint(current)) == bool(done):
		return
	frappe.db.set_value("Onboarding Step", step, "is_complete", 1 if done else 0)
