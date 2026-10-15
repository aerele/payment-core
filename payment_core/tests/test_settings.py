# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Payment Core Settings is the site-level home for behaviour that used to be
# decided per transaction. The auto-receipt switch: on -> every completed
# payment books a Capture Payment Receipt; off -> only callers that explicitly
# ask for one (an app's own order flow) do.

from unittest import skipUnless

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.mode import ledger_installed
from payment_core.utils import auto_receipt_enabled, create_payment_transaction


def _set_auto_receipt(value: int) -> None:
	frappe.db.set_single_value("Payment Core Settings", "auto_create_receipt", value)
	frappe.db.commit()


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestAutoReceiptSetting(FrappeTestCase):
	def setUp(self):
		self.addCleanup(_set_auto_receipt, 0)
		_set_auto_receipt(0)

	def _create(self, auto_receipt=False):
		return create_payment_transaction(
			reference_doctype="DocType",
			reference_docname="Payment Gateway",
			gateway="Test-Gateway",
			amount=100,
			auto_receipt=auto_receipt,
		)

	def test_setting_off_defaults_receipt_off(self):
		self.assertFalse(auto_receipt_enabled())
		self.assertEqual(self._create().auto_receipt, 0)

	def test_setting_on_forces_receipt_on(self):
		_set_auto_receipt(1)
		self.assertTrue(auto_receipt_enabled())
		self.assertEqual(self._create().auto_receipt, 1)

	def test_explicit_request_wins_when_setting_off(self):
		self.assertFalse(auto_receipt_enabled())
		self.assertEqual(self._create(auto_receipt=True).auto_receipt, 1)
