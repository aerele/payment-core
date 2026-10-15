# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Payment Receipt ledger + desk-action coverage. A fresh Note is used as the
# payable reference so tests stay inside payment_core (no consuming app needed).

from unittest import skipUnless
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from payment_core.mode import ledger_installed
from payment_core.utils import (
	cancel_payment_transaction,
	complete_payment_transaction,
	create_payment_gateway,
	create_payment_transaction,
	get_capture_balance,
	reconcile_payment_status,
	reconcile_reference_payments,
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
		auto_receipt=auto_receipt,
	)
	update_payment_transaction(transaction.name, status="Pending")
	return transaction.name


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestPaymentReceipts(FrappeTestCase):
	def test_capture_receipt_is_idempotent_per_transaction(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)

		first = record_payment_receipt(transaction=transaction, amount=100, method="Online")
		second = record_payment_receipt(transaction=transaction, amount=100, method="Online")
		self.assertEqual(first, second)

		rows = frappe.get_all("Payment Receipt", filters={"payment_transaction": transaction}, pluck="name")
		self.assertEqual(len(rows), 1)

	def test_reference_and_currency_default_from_transaction(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=250)

		name = record_payment_receipt(transaction=transaction, amount=250)
		receipt = frappe.get_doc("Payment Receipt", name)
		self.assertEqual(receipt.reference_doctype, "Note")
		self.assertEqual(receipt.reference_docname, reference)
		# falls back to the transaction's currency (site default at creation)
		self.assertEqual(
			receipt.currency, frappe.db.get_value("Payment Transaction", transaction, "currency")
		)
		self.assertEqual(receipt.gateway, "Stripe:Test")

	def test_refund_cannot_exceed_captured_minus_refunded(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100)
		record_payment_receipt(transaction=transaction, amount=100)

		record_payment_receipt(transaction=transaction, amount=40, entry_type="Refund")
		balance = get_capture_balance("Note", reference)
		self.assertEqual((balance["captured"], balance["refunded"], balance["net"]), (100, 40, 60))

		with self.assertRaises(frappe.ValidationError):
			record_payment_receipt(transaction=transaction, amount=70, entry_type="Refund")

	def test_refund_without_capture_is_rejected(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100)

		with self.assertRaises(frappe.ValidationError):
			record_payment_receipt(transaction=transaction, amount=10, entry_type="Refund")

	def test_second_transaction_may_capture_again(self):
		reference = _make_reference()
		first = _make_transaction(reference, amount=100)
		second = _make_transaction(reference, amount=50)

		record_payment_receipt(transaction=first, amount=100)
		record_payment_receipt(transaction=second, amount=50)

		self.assertEqual(flt(get_capture_balance("Note", reference)["captured"]), 150)

	def test_invalid_entry_type_is_rejected(self):
		reference = _make_reference()
		with self.assertRaises(frappe.ValidationError):
			record_payment_receipt(
				reference_doctype="Note", reference_docname=reference, amount=10, entry_type="Void"
			)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestTransactionDeskActions(FrappeTestCase):
	def test_complete_marks_completed_and_settles_reference(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)

		with patch("payment_core.utils.authorize_reference") as authorize:
			complete_payment_transaction(transaction, provider_reference="pi_test_123")

		authorize.assert_called_once_with("Note", reference, "Paid")
		row = frappe.db.get_value(
			"Payment Transaction", transaction, ["status", "provider_transaction_id", "paid_at"], as_dict=True
		)
		self.assertEqual(row.status, "Paid")
		self.assertEqual(row.provider_transaction_id, "pi_test_123")
		self.assertTrue(row.paid_at)

	def test_complete_rejects_already_completed(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)
		update_payment_transaction(transaction, status="Paid")

		with self.assertRaises(frappe.ValidationError):
			complete_payment_transaction(transaction)

	def test_cancel_only_open_transactions(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)

		cancel_payment_transaction(transaction)
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Cancelled")

		with self.assertRaises(frappe.ValidationError):
			cancel_payment_transaction(transaction)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestAutoReceipt(FrappeTestCase):
	def test_receipt_written_automatically_on_completion(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100, auto_receipt=True)

		update_payment_transaction(transaction, status="Paid", provider_transaction_id="pi_auto_1")

		receipts = frappe.get_all(
			"Payment Receipt",
			filters={"payment_transaction": transaction},
			fields=["entry_type", "amount", "provider_reference"],
		)
		self.assertEqual(len(receipts), 1)
		self.assertEqual(
			(receipts[0]["entry_type"], receipts[0]["amount"], receipts[0]["provider_reference"]),
			("Capture", 100, "pi_auto_1"),
		)

	def test_no_receipt_without_the_flag(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100)

		update_payment_transaction(transaction, status="Paid")

		self.assertFalse(frappe.db.exists("Payment Receipt", {"payment_transaction": transaction}))

	def test_double_completion_writes_exactly_one_receipt(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100, auto_receipt=True)

		update_payment_transaction(transaction, status="Paid")
		update_payment_transaction(transaction, status="Paid")

		self.assertEqual(
			len(
				frappe.get_all("Payment Receipt", filters={"payment_transaction": transaction}, pluck="name")
			),
			1,
		)

	def test_metadata_accumulates_across_updates(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)

		update_payment_transaction(transaction, metadata={"stripe_session_id": "cs_test_1"})
		update_payment_transaction(transaction, metadata={"stripe_payment_intent": "pi_test_1"})

		stored = frappe.parse_json(frappe.db.get_value("Payment Transaction", transaction, "metadata"))
		self.assertEqual(stored.get("stripe_session_id"), "cs_test_1")
		self.assertEqual(stored.get("stripe_payment_intent"), "pi_test_1")

	def test_desk_completion_records_the_confirmer(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100, auto_receipt=True)

		complete_payment_transaction(transaction, provider_reference="pi_desk_meta")

		stored = frappe.parse_json(frappe.db.get_value("Payment Transaction", transaction, "metadata"))
		self.assertEqual(stored.get("desk_confirmed_by"), frappe.session.user)

	def test_desk_completion_settles_reference_and_receipts(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100, auto_receipt=True)

		with patch("payment_core.utils.authorize_reference") as authorize:
			complete_payment_transaction(transaction, provider_reference="pi_desk_9")

		authorize.assert_called_once_with("Note", reference, "Paid")
		self.assertTrue(
			frappe.db.exists("Payment Receipt", {"payment_transaction": transaction, "entry_type": "Capture"})
		)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestTransactionCustomerAndMethod(FrappeTestCase):
	def test_create_records_explicit_payment_method(self):
		reference = _make_reference()
		transaction = create_payment_transaction(
			reference_doctype="Note",
			reference_docname=reference,
			gateway="Stripe:Test",
			amount=100,
			payment_method="UPI",
		)
		self.assertEqual(
			frappe.db.get_value("Payment Transaction", transaction.name, "payment_method"), "UPI"
		)

	def test_customer_resolved_from_email_via_hook(self):
		with patch("payment_core.utils.get_customer_doctype", return_value="User"):
			transaction = create_payment_transaction(
				reference_doctype="Note",
				reference_docname=_make_reference(),
				gateway="Stripe:Test",
				amount=100,
				customer_email="admin@example.com",
			)

		row = frappe.db.get_value(
			"Payment Transaction", transaction.name, ["customer_doctype", "customer"], as_dict=True
		)
		self.assertEqual(row.customer_doctype, "User")
		self.assertEqual(row.customer, "Administrator")

	def test_provider_customer_id_on_create_and_update(self):
		reference = _make_reference()
		transaction = create_payment_transaction(
			reference_doctype="Note",
			reference_docname=reference,
			gateway="Stripe:Test",
			amount=100,
			provider_customer_id="cus_test_initial",
		)
		self.assertEqual(
			frappe.db.get_value("Payment Transaction", transaction.name, "provider_customer_id"),
			"cus_test_initial",
		)

		update_payment_transaction(transaction.name, provider_customer_id="cus_test_final")
		self.assertEqual(
			frappe.db.get_value("Payment Transaction", transaction.name, "provider_customer_id"),
			"cus_test_final",
		)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestSuccessPageReconcile(FrappeTestCase):
	def test_open_transaction_reconciled_via_gateway_controller(self):
		create_payment_gateway("Test")
		reference = _make_reference()
		transaction = _make_transaction(reference)

		controller = MagicMock()
		with patch("payment_core.utils.get_payment_gateway_controller", return_value=controller):
			reconcile_reference_payments("Note", reference, retries=0, delay=0)

		controller.reconcile_transaction.assert_called_once_with(transaction)

	def test_settled_transaction_is_not_reconciled(self):
		create_payment_gateway("Test")
		reference = _make_reference()
		transaction = _make_transaction(reference)
		update_payment_transaction(transaction, status="Paid")

		controller = MagicMock()
		with patch("payment_core.utils.get_payment_gateway_controller", return_value=controller):
			reconcile_reference_payments("Note", reference, retries=0, delay=0)

		controller.reconcile_transaction.assert_not_called()

	def test_controller_without_reconcile_is_ignored(self):
		create_payment_gateway("Test")
		reference = _make_reference()
		_make_transaction(reference)

		controller = MagicMock(spec=["unrelated_method"])
		with patch("payment_core.utils.get_payment_gateway_controller", return_value=controller):
			reconcile_reference_payments("Note", reference, retries=0, delay=0)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestReconcilePaymentStatusEndpoint(FrappeTestCase):
	def test_settles_and_returns_latest_status(self):
		create_payment_gateway("Test")
		reference = _make_reference()
		transaction = _make_transaction(reference)

		controller = MagicMock()
		controller.reconcile_transaction.side_effect = lambda name: update_payment_transaction(
			name, status="Paid"
		)
		with patch("payment_core.utils.get_payment_gateway_controller", return_value=controller):
			status = reconcile_payment_status(doctype="Note", docname=reference)

		self.assertEqual(status, "Paid")
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Paid")

	def test_returns_empty_without_transactions(self):
		reference = _make_reference()
		self.assertEqual(reconcile_payment_status(doctype="Note", docname=reference), "")
