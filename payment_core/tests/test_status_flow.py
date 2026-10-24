# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Status lifecycle: forward-only guard, cancel persistence, capture
# validation, no-oracle guest endpoint.

from unittest import skipUnless
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from payment_core.mode import ledger_installed
from payment_core.payment_ledger.status_flow import PaymentTransactionStatus
from payment_core.utils import (
	cancel_payment_transaction,
	create_payment_gateway,
	create_payment_transaction,
	ensure_reference_transaction,
	reconcile_payment_status,
	record_payment_receipt,
	refund_payment_transaction,
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


def _capture(transaction, amount):
	"""Insert and submit one Capture receipt directly (multiple per transaction)."""
	reference_doctype, reference_docname = frappe.db.get_value(
		"Payment Transaction", transaction, ["reference_doctype", "reference_docname"]
	)
	receipt = frappe.get_doc(
		{
			"doctype": "Payment Receipt",
			"payment_transaction": transaction,
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
			"entry_type": "Capture",
			"amount": amount,
		}
	).insert(ignore_permissions=True)
	receipt.submit()
	return receipt.name


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

	def test_refunded_transaction_ignores_late_paid(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100, auto_receipt=True)
		update_payment_transaction(transaction, status="Paid")
		record_payment_receipt(transaction=transaction, amount=100, entry_type="Refund")
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Refunded")

		update_payment_transaction(transaction, status="Paid")
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Refunded")

	def test_no_alert_for_stale_settled_status(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100, auto_receipt=True)
		update_payment_transaction(transaction, status="Paid")

		# the money IS booked; a "decide whether to refund" alarm would invite mistakes
		with (
			patch("frappe.log_error") as log_error,
			patch("payment_core.payment_ledger.status_flow.alert_payment_managers") as alert,
		):
			update_payment_transaction(transaction, status="Partially Paid")

		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Paid")
		log_error.assert_not_called()
		alert.assert_not_called()

	def test_cancel_of_settled_transaction_is_blocked(self):
		# auto_receipt off: a Paid transaction carries no receipts, so only
		# the status check can stop the desk Cancel button
		reference = _make_reference()
		transaction = _make_transaction(reference)
		update_payment_transaction(transaction, status="Paid")

		with self.assertRaises(frappe.ValidationError):
			cancel_payment_transaction(transaction)
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Paid")

	def test_cancelled_transaction_is_frozen(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)
		cancel_payment_transaction(transaction)

		update_payment_transaction(transaction, status="Paid")
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Cancelled")

	def test_money_on_cancelled_transaction_alerts_and_is_not_booked(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)
		cancel_payment_transaction(transaction)

		# assert on the calls, not the Error Log row: log_error swallows its
		# own failures (and may defer), so the row is not reliably persisted
		with (
			patch("frappe.log_error") as log_error,
			patch("payment_core.payment_ledger.status_flow.alert_payment_managers") as alert,
		):
			update_payment_transaction(transaction, status="Paid", paid_at=frappe.utils.now_datetime())

		row = frappe.db.get_value("Payment Transaction", transaction, ["status", "paid_at"], as_dict=True)
		self.assertEqual(row.status, "Cancelled")
		self.assertIsNone(row.paid_at)
		self.assertFalse(
			frappe.db.exists("Payment Receipt", {"payment_transaction": transaction, "docstatus": 1})
		)
		# the ignored money must be loud
		log_error.assert_called_once()
		self.assertEqual(log_error.call_args.kwargs.get("title"), "Payment received on frozen transaction")
		alert.assert_called_once()

	def test_failed_transaction_can_be_cancelled_from_desk(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)
		update_payment_transaction(transaction, status="Failed")

		cancel_payment_transaction(transaction)
		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Cancelled")

	def test_same_status_write_still_updates_outstanding(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100)
		_capture(transaction, 30)
		self.assertEqual(
			frappe.db.get_value(
				"Payment Transaction", transaction, ["status", "outstanding_amount"], as_dict=True
			),
			frappe._dict(status="Partially Paid", outstanding_amount=70),
		)

		# same status: outstanding must not go stale
		_capture(transaction, 30)
		self.assertEqual(
			frappe.db.get_value(
				"Payment Transaction", transaction, ["status", "outstanding_amount"], as_dict=True
			),
			frappe._dict(status="Partially Paid", outstanding_amount=40),
		)

	def test_capture_cancellation_partially_reopens_paid_transaction(self):
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100)
		first = _capture(transaction, 60)
		_capture(transaction, 40)
		self.assertEqual(
			frappe.db.get_value(
				"Payment Transaction", transaction, ["status", "outstanding_amount"], as_dict=True
			),
			frappe._dict(status="Paid", outstanding_amount=0),
		)

		# the receipts now justify Partially Paid, not frozen Paid
		frappe.get_doc("Payment Receipt", first).cancel()
		self.assertEqual(
			frappe.db.get_value(
				"Payment Transaction", transaction, ["status", "outstanding_amount"], as_dict=True
			),
			frappe._dict(status="Partially Paid", outstanding_amount=60),
		)

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

		# assert against the database: only a db_set survives on_cancel
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


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestRefundIdempotency(FrappeTestCase):
	def test_retried_refund_reuses_the_same_key(self):
		"""A retried request must reuse the idempotency key (position-based),
		so the provider cannot treat the retry as a second refund."""

		class StubController:
			declares_the_key = True

			def __init__(self):
				self.keys = []

			def refund_transaction(self, transaction, amount, reason, idempotency_key=None):
				self.keys.append(idempotency_key)
				return "re_" + frappe.generate_hash(length=6)

		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100, auto_receipt=True)
		update_payment_transaction(transaction, status="Paid")

		stub = StubController()
		with patch("payment_core.utils._get_gateway_controller_for_transaction", return_value=stub):
			# first attempt: the provider refunds, but the receipt write fails
			with (
				patch(
					"payment_core.utils.record_payment_receipt", side_effect=frappe.ValidationError("boom")
				),
				self.assertRaises(frappe.ValidationError),
			):
				refund_payment_transaction(transaction, amount=40, reason="damaged")
			# retry: same logical refund, no receipt written yet
			refund_payment_transaction(transaction, amount=40, reason="damaged")

		self.assertEqual(len(stub.keys), 2)
		self.assertEqual(stub.keys[0], stub.keys[1])
		self.assertEqual(stub.keys[0], f"pc-refund-{transaction}-1-40.0")


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestCaptureFloatNoise(FrappeTestCase):
	def test_exact_fill_captures_survive_float_noise(self):
		"""0.1 x 3 on 0.30 and 0.1 x 10 on 1.00 must fill exactly: without
		precision-aware compares the last capture trips over 0.0999... and
		the transaction never reaches Paid."""
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=0.30)
		for _ in range(3):
			_capture(transaction, 0.10)
		row = frappe.db.get_value(
			"Payment Transaction", transaction, ["status", "outstanding_amount"], as_dict=True
		)
		self.assertEqual(row.status, "Paid")
		self.assertEqual(row.outstanding_amount, 0)

		reference = _make_reference()
		transaction = _make_transaction(reference, amount=1.00)
		for _ in range(10):
			_capture(transaction, 0.10)
		row = frappe.db.get_value(
			"Payment Transaction", transaction, ["status", "outstanding_amount"], as_dict=True
		)
		self.assertEqual(row.status, "Paid")
		self.assertEqual(row.outstanding_amount, 0)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestPaidGuardAcrossGateways(FrappeTestCase):
	def test_already_paid_guard_spans_gateways(self):
		reference = _make_reference()
		transaction = _make_transaction(reference)  # gateway Stripe:Test
		update_payment_transaction(transaction, status="Paid")

		with self.assertRaises(frappe.ValidationError):
			ensure_reference_transaction("Note", reference, "Razorpay:Other")

	def test_partial_payment_charges_open_balance(self):
		reference = (
			frappe.get_doc({"doctype": "Note", "title": "100", "public": 1})
			.insert(ignore_permissions=True)
			.name
		)
		frappe.get_doc(
			{
				"doctype": "Payment Field Mapping",
				"reference_doctype": "Note",
				"mapping": [{"purpose": "amount", "reference_field": "title"}],
			}
		).insert(ignore_permissions=True)
		transaction = _make_transaction(reference, amount=100)
		_capture(transaction, 30)

		new = ensure_reference_transaction("Note", reference, "Razorpay:Other")
		self.assertEqual(flt(frappe.db.get_value("Payment Transaction", new, "amount")), 70)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestAuthorizeOncePerTransaction(FrappeTestCase):
	def test_reference_authorized_exactly_once(self):
		"""A status that returns to Paid (cancelled Refund receipt) must not
		settle the reference a second time - an order could be fulfilled twice."""
		reference = _make_reference()
		transaction = _make_transaction(reference, amount=100)
		receipts = "payment_core.payment_ledger.doctype.payment_receipt.payment_receipt"

		with patch(f"{receipts}.authorize_reference") as authorize:
			_capture(transaction, 100)  # receipt-driven Paid: authorize #1
			refund = record_payment_receipt(transaction=transaction, amount=100, entry_type="Refund")
			frappe.get_doc("Payment Receipt", refund).cancel()  # back to Paid

		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Paid")
		authorize.assert_called_once()


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestConcurrentIdempotencyKey(FrappeTestCase):
	def test_insert_race_returns_the_existing_row(self):
		"""Two requests with the same idempotency_key at the same time: the
		loser must get the winner's transaction, not a UniqueValidationError."""
		reference = _make_reference()
		first = create_payment_transaction(
			reference_doctype="Note",
			reference_docname=reference,
			gateway="Stripe:Test",
			amount=100,
			currency="INR",
			idempotency_key="race-key-1",
		)

		original = frappe.db.get_value

		def miss_first_lookup(doctype, filters=None, *args, **kwargs):
			# only the idempotency pre-check misses; the post-clash re-fetch reads
			if isinstance(filters, dict) and filters.get("idempotency_key") == "race-key-1":
				miss_first_lookup.calls += 1
				if miss_first_lookup.calls == 1:
					return None
				# the re-fetch must be a locking read: a plain one uses the
				# request's old snapshot and misses the winner's committed row
				miss_first_lookup.refetch_was_locking = bool(kwargs.get("for_update"))
			return original(doctype, filters, *args, **kwargs)

		miss_first_lookup.calls = 0
		miss_first_lookup.refetch_was_locking = False
		with patch("payment_core.utils.frappe.db.get_value", side_effect=miss_first_lookup):
			second = create_payment_transaction(
				reference_doctype="Note",
				reference_docname=reference,
				gateway="Stripe:Test",
				amount=100,
				currency="INR",
				idempotency_key="race-key-1",
			)

		self.assertEqual(second.name, first.name)
		self.assertTrue(miss_first_lookup.refetch_was_locking)
