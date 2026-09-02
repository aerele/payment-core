# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Regression suite for the Payment Request resolver redirect. ERPNext's own
# methods must keep their exact controller-call contracts while resolving
# through payment_core; these tests pin both.

from unittest.mock import MagicMock, patch

import erpnext.accounts.doctype.payment_request.payment_request as erpnext_payment_request
import frappe
from frappe.model.base_document import get_controller
from frappe.tests.utils import FrappeTestCase

import payment_core.utils as payment_core_utils
from payment_core.overrides.payment_request import PaymentRequest as OverridePaymentRequest


class TestPaymentRequestOverride(FrappeTestCase):
	def test_extension_is_registered_and_used_by_frappe(self):
		extensions = frappe.get_hooks("extend_doctype_class") or {}
		self.assertEqual(
			extensions.get("Payment Request"),
			["payment_core.overrides.payment_request.PaymentRequest"],
		)
		controller = get_controller("Payment Request")
		# extend_doctype_class builds a combined class with our extension first
		# in the MRO, ahead of ERPNext's base controller.
		self.assertTrue(issubclass(controller, OverridePaymentRequest))
		self.assertTrue(issubclass(controller, erpnext_payment_request.PaymentRequest))

	def test_resolvers_are_redirected_to_payment_core(self):
		self.assertIs(
			erpnext_payment_request._get_payment_gateway_controller,
			payment_core_utils.get_payment_gateway_controller,
		)
		self.assertIs(erpnext_payment_request._is_v2_gateway, payment_core_utils.is_v2_gateway)

	def _new_payment_request(self, **fields):
		doc = frappe.new_doc("Payment Request")
		doc.update(
			{
				"payment_request_type": "Inward",
				"party_type": "Customer",
				"party": "Test",
				"reference_doctype": "Sales Invoice",
				"reference_name": "SAL-ORD-TEST-00001",
				"grand_total": 100,
				"currency": "INR",
				"party_account_currency": "INR",
				"subject": "Payment for SAL-ORD-TEST-00001",
				"email_to": "buyer@example.com",
				"payment_gateway": "Stripe-Stripe",
				"mute_email": 1,
			}
		)
		doc.update(fields)
		return doc

	def test_get_payment_url_uses_payment_core_controller_and_contract(self):
		doc = self._new_payment_request()
		doc.name = "ACC-PRQ-TEST-00001"
		controller = MagicMock()
		controller.get_payment_url.return_value = "https://checkout.stripe.com/test"

		# Narrow fake: only the reference-document lookup is mocked; every other
		# get_value (meta loads, defaults) delegates to the real database so the
		# Meta cache isn't poisoned.
		real_get_value = frappe.db.get_value

		def reference_only(*args, **kwargs):
			doctype = kwargs.get("doctype") or (args[0] if args else None)
			name = kwargs.get("filters") or (args[1] if len(args) > 1 else None)
			if doctype == "Sales Invoice" and name == "SAL-ORD-TEST-00001":
				return frappe._dict({"company": "Test Co", "customer_name": "T C"})
			return real_get_value(*args, **kwargs)

		with (
			patch.object(frappe.db, "get_value", side_effect=reference_only),
			patch.object(
				erpnext_payment_request,
				"_get_payment_gateway_controller",
				return_value=controller,
			) as resolver,
		):
			url = doc.get_payment_url()

		self.assertEqual(url, "https://checkout.stripe.com/test")
		resolver.assert_called_once_with("Stripe-Stripe")
		controller.validate_transaction_currency.assert_called_once_with("INR")
		controller.get_payment_url.assert_called_once_with(
			**{
				"amount": 100.0,
				"title": "Test Co",
				"description": "Payment for SAL-ORD-TEST-00001",
				"reference_doctype": "Payment Request",
				"reference_docname": "ACC-PRQ-TEST-00001",
				"payer_email": "buyer@example.com",
				"payer_name": "T C",
				"order_id": "ACC-PRQ-TEST-00001",
				"currency": "INR",
				"payment_gateway": "Stripe-Stripe",
			}
		)

	def test_before_submit_routes_v1_without_payments_app(self):
		"""Submitting must not require the payments app: ERPNext's own dispatch
		 resolves v2 detection through the redirected helper, so the guard never
		fires and no stale message lands in frappe.message_log."""
		doc = self._new_payment_request()

		with (
			patch("frappe.get_installed_apps", return_value=["frappe", "erpnext", "payment_core"]),
			patch.object(erpnext_payment_request, "_is_v2_gateway", return_value=False) as v2,
			patch.object(OverridePaymentRequest, "set_payment_request_url") as set_url,
		):
			doc.before_submit()

		v2.assert_called_once_with("Stripe-Stripe")
		set_url.assert_called_once_with()
		self.assertEqual(doc.status, "Requested")
		self.assertFalse(
			any("payments app is not installed" in str(m) for m in frappe.local.message_log),
			f"guard message leaked into message_log: {frappe.local.message_log}",
		)

	def test_before_submit_dispatches_v2_when_payment_core_marks_gateway_v2(self):
		doc = self._new_payment_request()

		with (
			patch.object(erpnext_payment_request, "_is_v2_gateway", return_value=True),
			patch.object(OverridePaymentRequest, "_process_v2_gateway") as process_v2,
			patch.object(OverridePaymentRequest, "set_payment_request_url") as set_url,
		):
			doc.before_submit()

		process_v2.assert_called_once_with()
		set_url.assert_not_called()

	def test_before_submit_phone_channel_routes_to_request_phone_payment(self):
		doc = self._new_payment_request(payment_channel="Phone")

		with (
			patch.object(erpnext_payment_request, "_is_v2_gateway", return_value=False),
			patch.object(OverridePaymentRequest, "request_phone_payment") as phone,
			patch.object(OverridePaymentRequest, "set_payment_request_url") as set_url,
		):
			doc.before_submit()

		phone.assert_called_once_with()
		set_url.assert_not_called()

	def test_payment_gateway_validation_uses_payment_core_controller(self):
		doc = self._new_payment_request()
		controller = MagicMock()
		controller.on_payment_request_submission.return_value = "custom_redirect"

		with patch.object(
			erpnext_payment_request,
			"_get_payment_gateway_controller",
			return_value=controller,
		):
			self.assertEqual(doc.payment_gateway_validation(), "custom_redirect")

	def test_create_subscription_dispatches_via_payment_core_registry(self):
		doc = self._new_payment_request()
		handler = MagicMock(return_value={"subscription": "sub_test"})
		data = {"reference_docname": "ACC-PRQ-TEST-00001"}

		with (
			patch(
				"payment_core.api.subscriptions.frappe.get_hooks",
				return_value={"stripe": "fake.module.handler"},
			),
			patch("payment_core.api.subscriptions.frappe.get_attr", return_value=handler),
		):
			result = doc.create_subscription("stripe", "Stripe", data)

		self.assertEqual(result, {"subscription": "sub_test"})
		handler.assert_called_once_with("Stripe", data)
