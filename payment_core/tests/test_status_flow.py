# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Status lifecycle coverage: the forward-only guard, the cancel persistence
# (frappe saves the row before on_cancel, so the write must be a db_set),
# capture-vs-transaction validation and the guest endpoint's no-oracle rule.

from unittest import skipUnless
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.mode import ledger_installed
from payment_core.payment_ledger.status_flow import PaymentTransactionStatus
from payment_core.utils import (
	cancel_payment_transaction,
	create_payment_gateway,
	create_payment_transaction,
	reconcile_payment_status,
	record_payment_receipt,
	update_payment_transaction,
)


def _make_reference():
	"""A unique payable-looking reference document per test (rolled back)."""
	return (
		frappe.get_doc({"doctype": "Note", "title": frappe.generate_hash(length=8), "public": 1})
		.insert(ignore_permissions=True)
		.name
	)


def _make_transaction(reference_docname, amount=100, auto_receipt=False):
	transaction = create_payment_transaction(
		reference_doctype="Note",
		reference_docname=reference_docname,
		gateway="Stripe:Test",
		amount=amount,
		currency="INR",
		auto_receipt=auto_receipt,
	)
	update_payment_transaction(transaction.name, status="Pending")
	return transaction.name


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestStatusFlow(FrappeTestCase):
	def test_settled_transaction_cannot_regress(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)
		update_payment_transaction(transaction, status="Paid")

		for stale in ("Initiated", "Failed", "Requested"):
			update_payment_transaction(transaction, status=stale)
			self.assertEqual(
				frappe.db.get_value("Payment Transaction", transaction, "status"),
				"Paid",
				f"Paid must not regress to {stale}",
			)

	def test_late_capture_after_expiry_fail_is_allowed(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)
		update_payment_transaction(transaction, status="Failed")

		update_payment_transaction(transaction, status="Paid")
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Paid")

	def test_cancelled_transaction_is_frozen(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)
		cancel_payment_transaction(transaction)

		update_payment_transaction(transaction, status="Paid")
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Cancelled")

	def test_assert_transition_throws_on_regression(self):
		with self.assertRaises(frappe.ValidationError):
			PaymentTransactionStatus.assert_transition("Paid", "Initiated")

	def test_receipt_cancellation_reopens_settled_transaction(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100, auto_receipt=True)
		update_payment_transaction(transaction, status="Paid")
		receipt = frappe.db.get_value(
			"Payment Receipt",
			{"payment_transaction": transaction, "entry_type": "Capture", "docstatus": 1},
			"name",
		)
		self.assertTrue(receipt)

		frappe.get_doc("Payment Receipt", receipt).cancel()
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Initiated")


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestCancelPersistence(FrappeTestCase):
	def test_submitted_cancel_persists_status(self):
		create_payment_gateway("Test")
		reference = _make_reference()
		transaction = _make_transaction(reference)

		controller = MagicMock()
		controller.get_payment_url = lambda **kwargs: "https://checkout.test/pay"
		with patch("payment_core.utils.get_payment_gateway_controller", return_value=controller):
			doc = frappe.get_doc("Payment Transaction", transaction)
			doc.submit()
			doc.cancel()

		# read from the database, not the in-memory object: frappe persists
		# the row *before* on_cancel runs, so only a db_set survives it
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Cancelled")


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestCaptureValidation(FrappeTestCase):
	def test_capture_beyond_outstanding_is_rejected(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100)
		record_payment_receipt(transaction=transaction, amount=100)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Payment Receipt",
					"payment_transaction": transaction,
					"entry_type": "Capture",
					"amount": 50,
				}
			).insert(ignore_permissions=True)

	def test_capture_currency_mismatch_is_rejected(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Payment Receipt",
					"payment_transaction": transaction,
					"entry_type": "Capture",
					"amount": 100,
					"currency": "USD",
				}
			).insert(ignore_permissions=True)

	def test_capture_reference_mismatch_is_rejected(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100)

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Payment Receipt",
					"payment_transaction": transaction,
					"reference_doctype": "ToDo",
					"reference_docname": "TODO-00001",
					"entry_type": "Capture",
					"amount": 100,
				}
			).insert(ignore_permissions=True)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestReconcileStatusOracle(FrappeTestCase):
	def test_unknown_reference_returns_empty_without_leaking_existence(self):
		# previously threw PermissionError for a missing document, letting
		# guests probe whether any doctype/name pair exists
		self.assertEqual(reconcile_payment_status(doctype="User", docname="nobody@example.com"), "")
		self.assertEqual(reconcile_payment_status(doctype="Note", docname="NOTE-00000"), "")
