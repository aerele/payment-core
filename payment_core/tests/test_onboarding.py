# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT
#
# The onboarding sync converges the "Get payments ready" steps with real
# site state; these tests pin each convergence rule.

from unittest import skipUnless
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.mode import is_gateway_only, ledger_installed
from payment_core.onboarding import (
	GATEWAY_STEP,
	TEST_PAYMENT_STEP,
	WEBHOOK_STEP,
	sync_onboarding_steps,
)

STEPS = (GATEWAY_STEP, WEBHOOK_STEP, TEST_PAYMENT_STEP)


class _Row:
	"""Minimal gateway row stand-in (only the sync reads the name)."""

	def __init__(self, name):
		self.name = name


class _Controller:
	"""Gateway controller stand-in; exposes only what it is given."""

	def __init__(self, is_webhook_configured=None):
		if is_webhook_configured is not None:
			self.is_webhook_configured = is_webhook_configured


@skipUnless(frappe.db.exists("Onboarding Step", GATEWAY_STEP), "onboarding fixtures not installed")
class TestOnboardingSync(FrappeTestCase):
	def setUp(self):
		for step in STEPS:
			frappe.db.set_value("Onboarding Step", step, "is_complete", 0)

	def _states(self):
		return {step: frappe.db.get_value("Onboarding Step", step, "is_complete") for step in STEPS}

	def test_no_gateway_leaves_all_steps_undone(self):
		with patch("payment_core.onboarding._has_a_captured_payment", return_value=False):
			sync_onboarding_steps(controllers=[])

		self.assertEqual(self._states(), {step: 0 for step in STEPS})

	def test_gateway_without_signal_keeps_webhook_step_undone(self):
		"""No controller exposes is_webhook_configured: the step must not
		assume configuration and stay undone."""
		controllers = [(_Row("GW-1"), _Controller())]

		with patch("payment_core.onboarding._has_a_captured_payment", return_value=False):
			sync_onboarding_steps(controllers=controllers)

		states = self._states()
		self.assertEqual(states[GATEWAY_STEP], 1)
		self.assertEqual(states[WEBHOOK_STEP], 0)

	def test_gateway_reporting_unconfigured_webhook_keeps_step_undone(self):
		controllers = [(_Row("GW-1"), _Controller(is_webhook_configured=lambda: False))]

		with patch("payment_core.onboarding._has_a_captured_payment", return_value=False):
			sync_onboarding_steps(controllers=controllers)

		self.assertEqual(self._states()[WEBHOOK_STEP], 0)

	def test_all_reporting_gateways_configured_tick_the_step(self):
		controllers = [
			(_Row("GW-1"), _Controller(is_webhook_configured=lambda: True)),
			(_Row("GW-2"), _Controller(is_webhook_configured=lambda: True)),
		]

		with patch("payment_core.onboarding._has_a_captured_payment", return_value=False):
			sync_onboarding_steps(controllers=controllers)

		self.assertEqual(self._states()[WEBHOOK_STEP], 1)

	def test_one_unconfigured_gateway_blocks_the_step(self):
		controllers = [
			(_Row("GW-1"), _Controller(is_webhook_configured=lambda: True)),
			(_Row("GW-2"), _Controller(is_webhook_configured=lambda: False)),
		]

		with patch("payment_core.onboarding._has_a_captured_payment", return_value=False):
			sync_onboarding_steps(controllers=controllers)

		self.assertEqual(self._states()[WEBHOOK_STEP], 0)


@skipUnless(ledger_installed(), "capture receipt case needs the shared ledger")
class TestCaptureReceiptTicksTestPayment(FrappeTestCase):
	def test_submitted_capture_receipt_sets_step_done(self):
		if not frappe.db.exists("Onboarding Step", TEST_PAYMENT_STEP):
			self.skipTest("onboarding fixtures not installed")
		frappe.db.set_value("Onboarding Step", TEST_PAYMENT_STEP, "is_complete", 0)

		# db_insert, not insert(): only the facts the sync reads matter here
		receipt = frappe.new_doc("Payment Receipt")
		receipt.update({"entry_type": "Capture", "amount": 100})
		receipt.name = frappe.generate_hash("PC Onboarding Receipt", 10)
		receipt.docstatus = 1
		receipt.db_insert()

		try:
			sync_onboarding_steps(controllers=[])
			self.assertEqual(frappe.db.get_value("Onboarding Step", TEST_PAYMENT_STEP, "is_complete"), 1)
		finally:
			frappe.db.delete("Payment Receipt", {"name": receipt.name})


@skipUnless(is_gateway_only(), "manual-entry case needs ERPNext (gateway-only site)")
class TestManualEntryDoesNotTickTestPayment(FrappeTestCase):
	def setUp(self):
		if not frappe.db.exists("Onboarding Step", TEST_PAYMENT_STEP):
			self.skipTest("onboarding fixtures not installed")
		frappe.db.set_value("Onboarding Step", TEST_PAYMENT_STEP, "is_complete", 0)
		# FrappeTestCase rolls this back: neutralize any pre-existing gateway
		# requests so the REAL query sees only this test's rows (dev benches
		# carry real settlements that would otherwise tick the step)
		PaymentRequest = frappe.qb.DocType("Payment Request")
		frappe.qb.update(PaymentRequest).set(PaymentRequest.payment_gateway, None).where(
			PaymentRequest.payment_gateway.notnull()
		).run()

	def _make_payment_entry(self, reference_no):
		entry = frappe.new_doc("Payment Entry")
		entry.update(
			{
				"payment_type": "Receive",
				"reference_no": reference_no,
				"paid_amount": 100,
			}
		)
		entry.name = frappe.generate_hash("PC Onboarding PE", 10)
		entry.docstatus = 1
		entry.db_insert()
		return entry.name

	def _make_payment_request(self, payment_gateway=None):
		# db_insert, not insert(): the sync only reads name + payment_gateway
		request = frappe.new_doc("Payment Request")
		request.update({"payment_gateway": payment_gateway})
		request.name = frappe.generate_hash("PC Onboarding PR", 10)
		request.db_insert()
		return request.name

	def _step(self):
		return frappe.db.get_value("Onboarding Step", TEST_PAYMENT_STEP, "is_complete")

	def test_manual_entry_without_request_does_not_tick(self):
		manual = self._make_payment_entry(reference_no="BANK-TRANSFER-1")
		try:
			sync_onboarding_steps(controllers=[])
			self.assertEqual(self._step(), 0)
		finally:
			frappe.db.delete("Payment Entry", {"name": manual})

	def test_manual_entry_from_gatewayless_request_does_not_tick(self):
		"""A hand-recorded bank transfer against a request without a gateway
		is still not a gateway payment."""
		request = self._make_payment_request(payment_gateway=None)
		entry = self._make_payment_entry(reference_no=request)
		try:
			sync_onboarding_steps(controllers=[])
			self.assertEqual(self._step(), 0)
		finally:
			frappe.db.delete("Payment Entry", {"name": entry})
			frappe.db.delete("Payment Request", {"name": request})

	def test_gateway_settlement_ticks_the_step(self):
		"""The positive control: a submitted PE referencing a gateway-backed
		request is a gateway payment."""
		request = self._make_payment_request(payment_gateway="Stripe-Test")
		entry = self._make_payment_entry(reference_no=request)
		try:
			sync_onboarding_steps(controllers=[])
			self.assertEqual(self._step(), 1)
		finally:
			frappe.db.delete("Payment Entry", {"name": entry})
			frappe.db.delete("Payment Request", {"name": request})
