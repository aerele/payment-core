# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# P0 stabilisation coverage: permission guards, ledger lifecycle (delete/update
# re-sync, trash guards) and the Refunded transition.

from unittest import skipUnless
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.mode import ledger_installed
from payment_core.utils import (
	cancel_payment_transaction,
	complete_payment_transaction,
	create_payment_transaction,
	record_payment_receipt,
	update_payment_transaction,
)


def _make_note(title=None):
	return (
		frappe.get_doc({"doctype": "Note", "title": title or frappe.generate_hash(length=8), "public": 1})
		.insert(ignore_permissions=True)
		.name
	)


def _make_transaction(amount=100):
	transaction = create_payment_transaction(
		reference_doctype="Note",
		reference_docname=_make_note(),
		gateway="Stripe:Test",
		amount=amount,
	)
	update_payment_transaction(transaction.name, status="Pending")
	return transaction.name


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestPermissionGuards(FrappeTestCase):
	def test_desk_actions_require_write_permission(self):
		transaction = _make_transaction()
		tester = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"noperms{frappe.generate_hash(length=4).lower()}@example.com",
				"first_name": "NoPerms",
				"user_type": "System User",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "User", tester.name, force=True)

		frappe.set_user(tester.email)
		self.addCleanup(frappe.set_user, "Administrator")
		with self.assertRaises(frappe.PermissionError):
			complete_payment_transaction(transaction)
		with self.assertRaises(frappe.PermissionError):
			cancel_payment_transaction(transaction)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestLedgerLifecycle(FrappeTestCase):
	def test_capture_delete_blocked_when_refunds_rely_on_it(self):
		transaction = _make_transaction()
		capture = record_payment_receipt(transaction=transaction, amount=100)
		record_payment_receipt(transaction=transaction, amount=40, entry_type="Refund")

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Payment Receipt", capture)

	def test_capture_delete_recomputes_outstanding(self):
		transaction = _make_transaction()
		capture = record_payment_receipt(transaction=transaction, amount=40)

		# receipts are submitted vouchers: cancel, then delete
		frappe.get_doc("Payment Receipt", capture).cancel()
		frappe.delete_doc("Payment Receipt", capture)

		row = frappe.db.get_value(
			"Payment Transaction", transaction, ["status", "outstanding_amount"], as_dict=True
		)
		self.assertEqual(row.status, "Initiated")
		self.assertEqual(row.outstanding_amount, 100)

	def test_transaction_delete_blocked_with_receipts(self):
		transaction = _make_transaction()
		record_payment_receipt(transaction=transaction, amount=10)

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Payment Transaction", transaction)

	def test_transaction_validate_recomputes_outstanding(self):
		transaction = _make_transaction()
		record_payment_receipt(transaction=transaction, amount=30)

		doc = frappe.get_doc("Payment Transaction", transaction)
		doc.amount = 120
		doc.save(ignore_permissions=True)

		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "outstanding_amount"), 90)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestRefundedTransition(FrappeTestCase):
	def test_full_refund_marks_transaction_refunded(self):
		transaction = _make_transaction()
		record_payment_receipt(transaction=transaction, amount=100)
		update_payment_transaction(transaction, status="Paid")

		record_payment_receipt(transaction=transaction, amount=100, entry_type="Refund")

		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Refunded")

	def test_partial_refund_keeps_completed(self):
		transaction = _make_transaction()
		record_payment_receipt(transaction=transaction, amount=100)
		update_payment_transaction(transaction, status="Paid")

		record_payment_receipt(transaction=transaction, amount=40, entry_type="Refund")

		self.assertEqual(frappe.db.get_value("Payment Transaction", transaction, "status"), "Paid")


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestRefundEndpoint(FrappeTestCase):
	def _paid_transaction(self):
		transaction = _make_transaction()
		record_payment_receipt(transaction=transaction, amount=100)
		update_payment_transaction(transaction, status="Paid")
		return transaction

	def test_refund_records_receipt_idempotently(self):
		from unittest.mock import MagicMock, patch

		from payment_core.utils import refund_payment_transaction

		transaction = self._paid_transaction()
		controller = MagicMock()
		controller.refund_transaction.return_value = "re_test_1"
		with patch("payment_core.utils._get_gateway_controller_for_transaction", return_value=controller):
			first = refund_payment_transaction(transaction, amount=40, reason="damaged")
			second = refund_payment_transaction(transaction, amount=40)

		self.assertEqual(first, second)
		self.assertTrue(
			frappe.db.exists("Payment Receipt", {"provider_reference": "re_test_1", "entry_type": "Refund"})
		)

	def test_refund_rejects_unpaid_transaction(self):
		from unittest.mock import patch

		from payment_core.utils import refund_payment_transaction

		transaction = _make_transaction()  # left Pending on purpose
		with patch("payment_core.utils._get_gateway_controller_for_transaction", return_value=None):
			with self.assertRaises(frappe.ValidationError):
				refund_payment_transaction(transaction, amount=10)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestStaleSweep(FrappeTestCase):
	def test_sweep_expires_and_rechecks(self):
		from unittest.mock import MagicMock, patch

		from frappe.utils import add_days, now_datetime

		from payment_core.tasks import reconcile_stale_transactions

		stale = _make_transaction()  # older than the expiry window: must Fail
		frappe.db.set_value(
			"Payment Transaction", stale, "creation", add_days(now_datetime(), -5), update_modified=False
		)
		fresh = _make_transaction()  # within the window: only rechecked
		controller = MagicMock()
		with patch("payment_core.tasks._get_gateway_controller_for_transaction", return_value=controller):
			result = reconcile_stale_transactions(older_than_hours=0)

		self.assertEqual(frappe.db.get_value("Payment Transaction", stale, "status"), "Failed")
		self.assertEqual(frappe.db.get_value("Payment Transaction", fresh, "status"), "Initiated")
		self.assertGreaterEqual(result["expired"], 1)
		self.assertGreaterEqual(result["rechecked"], 1)
		controller.reconcile_transaction.assert_called()


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestWebhookLog(FrappeTestCase):
	def _deliver(self, event_id, payload=None, source="Stripe:Test"):
		from payment_core.webhooks import DUPLICATE, get_or_create_log

		return get_or_create_log(
			source=source,
			event_id=event_id,
			event_type="payment_intent.succeeded",
			payload=payload or {"id": event_id},
			provider_reference="pi_1",
		)

	def test_dedupe_and_failed_reprocess(self):
		from payment_core.webhooks import mark_failed, mark_processed

		log, duplicate = self._deliver("evt_1")
		self.assertIsNone(duplicate)
		mark_processed(log.name, reference_doctype="Note", reference_docname="N1")
		row = frappe.db.get_value(
			"Payment Webhook Log", log.name, ["status", "reference_docname"], as_dict=True
		)
		self.assertEqual((row.status, row.reference_docname), ("Processed", "N1"))

		_second, duplicate = self._deliver("evt_1")
		self.assertEqual(duplicate, {"status": "duplicate"})

		mark_failed(log.name, "boom")
		retried, duplicate = self._deliver("evt_1")
		self.assertIsNone(duplicate)
		self.assertEqual(retried.name, log.name)

	def test_event_ids_are_scoped_per_source(self):
		# two gateways may send the same event id: both are delivered, only a
		# repeat from the SAME source dedupes
		first, duplicate = self._deliver("evt_shared")
		self.assertIsNone(duplicate)
		second, duplicate = self._deliver("evt_shared", source="Razorpay:Test")
		self.assertIsNone(duplicate)
		self.assertNotEqual(first.name, second.name)
		_, duplicate = self._deliver("evt_shared")
		self.assertEqual(duplicate, {"status": "duplicate"})

	def test_statuses_are_scoped(self):
		from payment_core.webhooks import mark_processed

		log, _ = self._deliver("evt_2")
		mark_processed(log.name, status="Ignored")
		self.assertEqual(frappe.db.get_value("Payment Webhook Log", log.name, "status"), "Ignored")


STRIPE_INSTALLED = True
try:
	from stripe_payment.gateway.references import ensure_payment_transaction
except ImportError:
	STRIPE_INSTALLED = False


@skipUnless(STRIPE_INSTALLED, "stripe_payment not installed on this bench")
class TestStripeGuardedPaths(FrappeTestCase):
	def test_ensure_payment_transaction_skips_without_table(self):
		data = frappe._dict({"reference_doctype": "Note", "reference_docname": "N1"})
		with patch("frappe.db.table_exists", return_value=False):
			self.assertIsNone(ensure_payment_transaction(None, data))
		self.assertNotIn("payment_transaction", data)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestLedgerGuards(FrappeTestCase):
	def test_reconcile_status_returns_empty_without_ledger(self):
		from payment_core.utils import reconcile_payment_status

		with patch("frappe.db.table_exists", return_value=False):
			self.assertEqual(reconcile_payment_status("Note", "whatever"), "")

	def test_ledger_installed_reflects_site(self):
		from payment_core.mode import ledger_installed as site_ledger_installed

		self.assertEqual(site_ledger_installed(), frappe.db.table_exists("Payment Transaction"))
