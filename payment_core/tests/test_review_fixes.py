# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Regression tests for the code-review fixes: purge data-loss guard, capture
# serialization, refund pre-validation, failure alerts on the db.set_value
# path, and before_submit persistence of Requested + checkout URL.

from unittest import skipUnless
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.mode import ledger_installed
from payment_core.utils import (
	create_payment_transaction,
	initiate_transaction,
	record_payment_receipt,
	refund_payment_transaction,
	update_payment_transaction,
)

MODULE = "payment_core.utils"
NOTIFICATIONS = "payment_core.notifications"


def _make_transaction(amount=100, status="Draft", **overrides):
	doc = frappe.get_doc(
		{
			"doctype": "Payment Transaction",
			"reference_doctype": "DocType",
			"reference_docname": "Payment Gateway",
			"gateway": "Fake:fake-gateway",
			"amount": amount,
			"currency": "INR",
			"status": status,
			**overrides,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _capture(name, amount):
	return record_payment_receipt(transaction=name, amount=amount, entry_type="Capture", method="Online")


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestPurgeDataLossGuard(FrappeTestCase):
	def test_purge_raises_when_ledger_has_rows(self):
		from payment_core.ledger_gate import purge_ledger

		# any non-empty ledger table must block the purge
		with patch("payment_core.ledger_gate.is_gateway_only", return_value=True):
			with self.assertRaises(frappe.ValidationError):
				purge_ledger()

	def test_purge_proceeds_when_tables_absent(self):
		from payment_core.ledger_gate import purge_ledger

		with (
			patch("payment_core.ledger_gate.is_gateway_only", return_value=True),
			patch("payment_core.ledger_gate.frappe.db.table_exists", return_value=False),
			patch("payment_core.ledger_gate.frappe.db.exists", return_value=None),
			patch("payment_core.ledger_gate.frappe.get_all", return_value=[]),
			patch("payment_core.ledger_gate.frappe.db.commit"),
			patch("payment_core.ledger_gate.frappe.logger"),
		):
			purge_ledger()  # must not raise


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestCaptureSerialization(FrappeTestCase):
	def test_second_capture_returns_existing_receipt(self):
		doc = _make_transaction(status="Requested")
		first = _capture(doc.name, 100)
		second = _capture(doc.name, 100)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("Payment Receipt", {"payment_transaction": doc.name}), 1)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestRefundPreValidation(FrappeTestCase):
	def test_over_refund_throws_before_provider_call(self):
		doc = _make_transaction(status="Paid", amount=100)
		_capture(doc.name, 100)
		_refunded = record_payment_receipt(
			transaction=doc.name, amount=80, entry_type="Refund", method="Online"
		)
		controller = MagicMock()
		with (
			patch(f"{MODULE}._get_gateway_controller_for_transaction", return_value=controller),
			self.assertRaises(frappe.ValidationError),
		):
			refund_payment_transaction(doc.name, 50)  # only 20 refundable
		controller.refund_transaction.assert_not_called()

	def test_valid_refund_reaches_provider(self):
		doc = _make_transaction(status="Paid", amount=100)
		_capture(doc.name, 100)
		controller = MagicMock()
		controller.refund_transaction.return_value = "re_test_1"
		with patch(f"{MODULE}._get_gateway_controller_for_transaction", return_value=controller):
			refund_payment_transaction(doc.name, 30)
		controller.refund_transaction.assert_called_once()


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestFailureAlertOnRealPath(FrappeTestCase):
	def test_db_set_value_path_fires_alert(self):
		doc = _make_transaction(status="Initiated")
		with patch(f"{NOTIFICATIONS}.frappe.sendmail") as sendmail:
			update_payment_transaction(doc.name, status="Failed", error_message="declined")
		sendmail.assert_called_once()

	def test_no_alert_on_same_status_rewrite(self):
		doc = _make_transaction(status="Failed")
		frappe.db.set_value("Payment Transaction", doc.name, "error_message", "first", update_modified=False)
		with patch(f"{NOTIFICATIONS}.frappe.sendmail") as sendmail:
			update_payment_transaction(doc.name, status="Failed", error_message="second")
		sendmail.assert_not_called()


class FakeGatewayController:
	"""Minimal controller satisfying create_payment_url's contract."""

	def get_payment_url(self, **kwargs):
		return "https://checkout.fake.test/pay/cs_fake_123"


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestSubmitPersistsRequestedAndUrl(FrappeTestCase):
	def test_submit_writes_status_and_url_to_db(self):
		doc = _make_transaction()
		frappe.db.set_single_value("Payment Core Settings", "enable_email_flow", 0)
		self.addCleanup(frappe.db.set_single_value, "Payment Core Settings", "enable_email_flow", 0)
		with patch(
			"payment_core.payment_ledger.doctype.payment_transaction.payment_transaction.resolve_gateway_controller",
			return_value=FakeGatewayController(),
		):
			doc.submit()
			frappe.db.commit()
		row = frappe.db.get_value("Payment Transaction", doc.name, ["status", "checkout_url"], as_dict=True)
		self.assertEqual(row.status, "Requested")
		self.assertEqual(row.checkout_url, "https://checkout.fake.test/pay/cs_fake_123")

	def test_email_queued_on_submit_when_flow_enabled(self):
		frappe.db.set_single_value("Payment Core Settings", "enable_email_flow", 1)
		self.addCleanup(frappe.db.set_single_value, "Payment Core Settings", "enable_email_flow", 0)
		doc = _make_transaction(customer_email="buyer@example.com")
		frappe.db.after_commit.reset()
		with (
			patch(
				"payment_core.payment_ledger.doctype.payment_transaction.payment_transaction.resolve_gateway_controller",
				return_value=FakeGatewayController(),
			),
			patch(
				"payment_core.payment_ledger.doctype.payment_transaction.payment_transaction.send_payment_email"
			) as send,
		):
			doc.submit()
			frappe.db.after_commit.run()
		send.assert_called_once_with(doc.name)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestGuestInitiateTransaction(FrappeTestCase):
	def test_guest_session_can_initiate_checkout(self):
		"""Guest checkout (ensure_reference_transaction + initiate_transaction) must
		submit without desk permissions — regression for the buyer-facing
		PermissionError on the cart flow."""
		doc = _make_transaction()
		frappe.db.set_single_value("Payment Core Settings", "enable_email_flow", 0)
		self.addCleanup(frappe.db.set_single_value, "Payment Core Settings", "enable_email_flow", 0)
		frappe.set_user("Guest")
		try:
			with patch(
				"payment_core.payment_ledger.doctype.payment_transaction.payment_transaction.resolve_gateway_controller",
				return_value=FakeGatewayController(),
			):
				url = initiate_transaction(doc.name)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(url, "https://checkout.fake.test/pay/cs_fake_123")


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestCaptureIdempotencyIgnoresCancelledReceipt(FrappeTestCase):
	def test_cancelled_capture_receipt_books_a_fresh_one(self):
		"""A desk-cancelled capture must not satisfy capture idempotency.

		The exists-check filters docstatus, so a corrected (cancelled) receipt
		lets settlement book a replacement instead of returning the dead row
		while still authorizing the reference.
		"""
		transaction = _make_transaction().name
		first = record_payment_receipt(transaction=transaction, amount=100)
		frappe.get_doc("Payment Receipt", first).cancel()

		second = record_payment_receipt(transaction=transaction, amount=100)

		self.assertNotEqual(first, second)
		live = frappe.get_all(
			"Payment Receipt",
			filters={"payment_transaction": transaction, "entry_type": "Capture", "docstatus": 1},
			pluck="name",
		)
		self.assertEqual(live, [second])
