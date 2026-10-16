# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# The global email-flow switch: when Payment Core Settings enables it,
# submitting a Payment Transaction emails the buyer the checkout link with
# the reference document's print attached (ERPNext Payment Request parity).
# Disabled (default) the checkout link is used directly at the desk.

from unittest import skipUnless
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.mode import ledger_installed
from payment_core.utils import email_flow_enabled, send_payment_email

MODULE = "payment_core.utils"


def _set_email_flow(value: int) -> None:
	frappe.db.set_single_value("Payment Core Settings", "enable_email_flow", value)
	frappe.db.commit()


def _make_transaction(amount=500, customer_email="buyer@example.com", checkout_url=None):
	doc = frappe.get_doc(
		{
			"doctype": "Payment Transaction",
			"reference_doctype": "DocType",
			"reference_docname": "Payment Gateway",
			"gateway": "Test-Gateway",
			"amount": amount,
			"currency": "INR",
			"customer_email": customer_email,
			"payer_name": "Test Buyer",
			"checkout_url": checkout_url,
			"status": "Requested",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestEmailFlow(FrappeTestCase):
	def setUp(self):
		self.addCleanup(_set_email_flow, 0)
		_set_email_flow(0)

	def test_disabled_by_default(self):
		self.assertFalse(email_flow_enabled())

	def test_sends_link_with_reference_print(self):
		doc = _make_transaction(checkout_url="https://checkout.example.com/pay/cs_test_1")
		with (
			patch(f"{MODULE}.frappe.sendmail") as sendmail,
			patch(
				f"{MODULE}.frappe.attach_print", return_value={"fname": "f.pdf", "fcontent": b"x"}
			) as attach,
		):
			recipient = send_payment_email(doc.name)

		self.assertEqual(recipient, "buyer@example.com")
		sendmail.assert_called_once()
		kwargs = sendmail.call_args.kwargs
		self.assertEqual(kwargs["recipients"], "buyer@example.com")
		self.assertIn("Payment Gateway", kwargs["subject"])
		self.assertIn("https://checkout.example.com/pay/cs_test_1", kwargs["message"])
		attach.assert_called_once_with("DocType", "Payment Gateway", file_name="Payment Gateway")
		self.assertEqual(kwargs["attachments"], [{"fname": "f.pdf", "fcontent": b"x"}])

	def test_no_email_without_buyer_or_link(self):
		doc = _make_transaction(customer_email="", checkout_url="https://x.test/pay")
		with patch(f"{MODULE}.frappe.sendmail") as sendmail:
			self.assertIsNone(send_payment_email(doc.name))
		sendmail.assert_not_called()

	def test_attachment_failure_still_sends_link(self):
		doc = _make_transaction(checkout_url="https://checkout.example.com/pay/cs_test_2")
		with (
			patch(f"{MODULE}.frappe.sendmail") as sendmail,
			patch(f"{MODULE}.frappe.attach_print", side_effect=OSError("wkhtmltopdf unreachable")),
			patch(f"{MODULE}.frappe.log_error"),
		):
			recipient = send_payment_email(doc.name)

		self.assertEqual(recipient, "buyer@example.com")
		kwargs = sendmail.call_args.kwargs
		self.assertEqual(kwargs["attachments"], [])
		self.assertIn("https://checkout.example.com/pay/cs_test_2", kwargs["message"])

	def test_send_failure_is_logged_not_raised_for_auto_path(self):
		doc = _make_transaction(checkout_url="https://checkout.example.com/pay/cs_test_4")
		with (
			patch(f"{MODULE}.frappe.sendmail", side_effect=frappe.OutgoingEmailError("no account")),
			patch(f"{MODULE}.frappe.log_error"),
		):
			recipient = send_payment_email(doc.name)  # must not raise
		self.assertEqual(recipient, "buyer@example.com")

		with (
			patch(f"{MODULE}.frappe.sendmail", side_effect=frappe.OutgoingEmailError("no account")),
			patch(f"{MODULE}.frappe.log_error"),
			self.assertRaises(frappe.OutgoingEmailError),
		):
			send_payment_email(doc.name, raise_on_failure=True)

	def test_queue_payment_email_registers_after_commit(self):
		from payment_core.payment_ledger.doctype.payment_transaction.payment_transaction import (
			PaymentTransaction,
		)

		doc = _make_transaction(checkout_url="https://checkout.example.com/pay/cs_test_3")
		txn = frappe.get_doc("Payment Transaction", doc.name)
		frappe.db.after_commit.reset()
		with (
			patch(
				"payment_core.payment_ledger.doctype.payment_transaction.payment_transaction.email_flow_enabled",
				return_value=True,
			),
			patch(
				"payment_core.payment_ledger.doctype.payment_transaction.payment_transaction.send_payment_email"
			) as send,
		):
			txn.queue_payment_email()
			self.assertEqual(len(frappe.db.after_commit._functions), 1)
			frappe.db.after_commit.run()
		send.assert_called_once_with(doc.name)

		frappe.db.after_commit.reset()
		with (
			patch(
				"payment_core.payment_ledger.doctype.payment_transaction.payment_transaction.email_flow_enabled",
				return_value=False,
			),
			patch(
				"payment_core.payment_ledger.doctype.payment_transaction.payment_transaction.send_payment_email"
			) as send,
		):
			txn.queue_payment_email()
			frappe.db.after_commit.run()
		send.assert_not_called()


class TestInstallSummary(FrappeTestCase):
	def test_summary_prints_for_both_modes(self):
		from payment_core.install import print_install_summary

		with (
			patch("payment_core.install.is_gateway_only", return_value=False),
			patch("payment_core.install.gateway_only_reason", return_value=None),
			# simulate the ledger tables: on a gateway-only site (the ERPNext
			# CI leg) they are purged and the summary would print nothing
			patch("payment_core.install.frappe.db.table_exists", return_value=True),
			patch("payment_core.install.click.secho") as secho,
		):
			print_install_summary()
		text = " ".join(str(call.args[0]) for call in secho.call_args_list)
		self.assertIn("No app owns the payment flow here", text)
		self.assertIn("Payment Transaction", text)
		self.assertIn("Payment Receipt", text)
		self.assertIn("Payment Field Mapping", text)

		with (
			patch("payment_core.install.is_gateway_only", return_value=True),
			patch("payment_core.install.gateway_only_reason", return_value="ERPNext is installed"),
			patch("payment_core.install.click.secho") as secho,
		):
			print_install_summary()
		text = " ".join(str(call.args[0]) for call in secho.call_args_list)
		self.assertIn("gateway-only mode", text)
		self.assertIn("ERPNext is installed", text)
