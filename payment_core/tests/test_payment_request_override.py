# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Regression suite for the Payment Request resolver redirect. ERPNext's own
# methods must keep their exact controller-call contracts while resolving
# through payment_core; these tests pin both. payment_core runs with and
# without ERPNext — the whole module skips on sites without it.

from unittest import skipUnless
from unittest.mock import MagicMock, patch

import frappe
from frappe.model.base_document import get_controller
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

ERPNext_INSTALLED = "erpnext" in frappe.get_installed_apps()

if ERPNext_INSTALLED:
	import erpnext.accounts.doctype.payment_request.payment_request as erpnext_payment_request

	import payment_core.utils as payment_core_utils
	from payment_core.overrides.payment_request import PaymentRequest as OverridePaymentRequest


@skipUnless(ERPNext_INSTALLED, "ERPNext Payment Request integration is optional")
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

	@staticmethod
	def _ensure_erpnext_fixtures() -> tuple:
		"""Bootstrap the ERPNext masters this test needs on wizard-less sites.

		CI installs ERPNext without completing the setup wizard. erpnext's own
		BootStrapTestData installs its presets (tree roots, UOMs, warehouse
		types — inserted with explicit names, which Prompt autoname requires)
		and master data (company, customer, item, fiscal years) exactly the way
		its own test suite expects to find them. Only the payments side (a
		default Payment Gateway Account for make_payment_request) is ours.
		"""
		if not frappe.db.get_value("Company", {}):
			from erpnext.tests.utils import BootStrapTestData

			BootStrapTestData()

		company = frappe.db.get_value("Company", {}, "name")
		company_currency = frappe.db.get_value("Company", company, "default_currency") or "INR"
		abbr = frappe.db.get_value("Company", company, "abbr")

		from payment_core.utils import create_payment_gateway

		if not frappe.db.exists("Payment Gateway", "PayTest"):
			create_payment_gateway("PayTest")
		if not frappe.db.exists("Payment Gateway Account", {"is_default": 1}):
			frappe.get_doc(
				{
					"doctype": "Payment Gateway Account",
					"payment_gateway": "PayTest",
					"company": company,
					"payment_account": f"Cash - {abbr}",
					"currency": company_currency,
					"is_default": 1,
				}
			).insert(ignore_permissions=True)

		customer = frappe.db.get_value("Customer", {}, "name")
		item = frappe.db.get_value("Item", {"is_sales_item": 1}, "name")
		return company, customer, item, company_currency

	def test_authorize_reference_settles_pr_and_returns_no_redirect(self):
		"""The PR branch must not leak the Payment Entry document to callers.

		Gateways treat authorize_reference's return as a redirect route; the
		Payment Entry document settle_payment_request yields coerces into a
		bogus "Payment Entry (NAME)" URL that 404s after checkout.
		"""
		company, customer, item, company_currency = self._ensure_erpnext_fixtures()
		si = frappe.new_doc("Sales Invoice")
		si.customer = customer
		si.company = company
		si.currency = company_currency
		si.append("items", {"item_code": item, "qty": 1, "rate": 100})
		si.insert()
		si.submit()

		pr = erpnext_payment_request.make_payment_request(
			dt="Sales Invoice", dn=si.name, recipient_id=None, payment_type="Outward", mute=1
		)
		if isinstance(pr, dict):
			pr = frappe.get_doc("Payment Request", pr.get("name"))

		# simulate current ERPNext, whose PaymentRequest class defines its own
		# on_payment_authorized (reacting only to Authorized/Completed): the
		# duck-typed dispatch must NOT capture Payment Requests away from
		# payment_core's settlement
		with (
			patch.object(
				type(pr),
				"on_payment_authorized",
				lambda self, status=None: "must-not-leak",
				create=True,
			),
			patch.object(payment_core_utils, "settle_payment_request") as settle,
		):
			result = payment_core_utils.authorize_reference("Payment Request", pr.name, "Paid")

		self.assertIsNone(result)
		settle.assert_called_once()

	def test_multi_currency_pe_converts_charged_amount(self):
		"""Multi-currency: the PE books the charged amount converted at the
		reference's exchange rate, not the raw party-currency charge."""
		from frappe.utils import flt

		company, customer, item, company_currency = self._ensure_erpnext_fixtures()
		party_currency = "USD" if company_currency != "USD" else "EUR"
		si = frappe.new_doc("Sales Invoice")
		si.customer = customer
		si.company = company
		si.currency = party_currency
		si.conversion_rate = 83.0
		si.append("items", {"item_code": item, "qty": 1, "rate": 100})  # 100 party currency
		si.insert()
		si.submit()

		pr = erpnext_payment_request.make_payment_request(
			dt="Sales Invoice", dn=si.name, recipient_id=None, payment_type="Outward", mute=1
		)
		if isinstance(pr, dict):
			pr = frappe.get_doc("Payment Request", pr.get("name"))
		# settle only books submitted requests; keep submit quiet (email and
		# legacy URL creation need a web/gateway context this test doesn't have)
		pr.flags.mute_email = 1
		with patch.object(pr, "set_payment_request_url"):
			pr.submit()

		controller = MagicMock()
		controller.get_charged_amount = MagicMock(return_value=50.0)  # partial charge
		payment_entry = MagicMock()
		captured = []
		with (
			patch("payment_core.utils.get_payment_gateway_controller", return_value=controller),
			patch.object(
				type(pr),
				"create_payment_entry",
				new=lambda builder_self, submit=True: captured.append(flt(builder_self.outstanding_amount))
				or payment_entry,
			),
		):
			payment_core_utils.settle_payment_request(pr, controller=controller)

		# 50 (party currency) * 83 (reference exchange rate), rounded to
		# currency precision, handed to the builder as the outstanding
		self.assertEqual(flt(captured[-1]), flt(50.0 * 83.0, 2))

	def test_multi_currency_outstanding_party_domain(self):
		"""A party account in the request currency (foreign account) keeps the
		outstanding as grand_total and never converts: PE books 40, not 3320."""
		from frappe.utils import flt

		pr = self._make_multi_currency_pr()
		# ERPNext's rule: party account currency == request currency -> the
		# outstanding stays grand_total and no conversion happens
		pr.db_set("party_account_currency", "USD")
		pr.db_set("outstanding_amount", 100)

		controller = MagicMock()
		controller.get_charged_amount = MagicMock(return_value=40.0)  # partial, party currency
		payment_entry = MagicMock()
		captured = []
		with (
			patch("payment_core.utils.get_payment_gateway_controller", return_value=controller),
			patch.object(
				type(pr),
				"create_payment_entry",
				new=lambda builder_self, submit=True: captured.append(flt(builder_self.outstanding_amount))
				or payment_entry,
			),
		):
			payment_core_utils.settle_payment_request(pr, controller=controller)

		self.assertEqual(flt(captured[-1]), 40.0)

	def _make_multi_currency_pr(self):
		company, customer, item, company_currency = self._ensure_erpnext_fixtures()
		party_currency = "USD" if company_currency != "USD" else "EUR"
		si = frappe.new_doc("Sales Invoice")
		si.customer = customer
		si.company = company
		si.currency = party_currency
		si.conversion_rate = 83.0
		si.append("items", {"item_code": item, "qty": 1, "rate": 100})  # 100 party currency
		si.insert()
		si.submit()

		pr = erpnext_payment_request.make_payment_request(
			dt="Sales Invoice", dn=si.name, recipient_id=None, payment_type="Outward", mute=1
		)
		if isinstance(pr, dict):
			pr = frappe.get_doc("Payment Request", pr.get("name"))
		pr.flags.mute_email = 1
		with patch.object(pr, "set_payment_request_url"):
			pr.submit()
		return pr

	def _make_single_currency_pr(self):
		company, customer, item, company_currency = self._ensure_erpnext_fixtures()
		si = frappe.new_doc("Sales Invoice")
		si.customer = customer
		si.company = company
		si.currency = company_currency
		si.append("items", {"item_code": item, "qty": 1, "rate": 100})
		si.insert()
		si.submit()

		pr = erpnext_payment_request.make_payment_request(
			dt="Sales Invoice", dn=si.name, recipient_id=None, payment_type="Outward", mute=1
		)
		if isinstance(pr, dict):
			pr = frappe.get_doc("Payment Request", pr.get("name"))
		pr.flags.mute_email = 1
		with patch.object(pr, "set_payment_request_url"):
			pr.submit()
		return pr

	def _settle(self, pr, charged):
		"""Settle with a mocked gateway reporting `charged` (None = unknown).

		The Payment Entry builder is mocked too: these tests assert
		payment_core's amount decision - the reference allocation it scales
		for a partial charge. The request's status write-back belongs to
		ERPNext's PE submit and is covered end to end by
		test_settle_pays_only_the_request_the_buyer_paid below.
		"""
		controller = MagicMock()
		controller.get_charged_amount = MagicMock(return_value=charged)
		payment_entry = MagicMock()

		def _capture_builder_amount(builder_self, submit=True):
			# the charged amount reaches ERPNext's builder as the in-memory
			# outstanding; capture it at build time
			captured.append(flt(builder_self.outstanding_amount))
			return payment_entry

		captured = []
		with (
			patch("payment_core.utils.get_payment_gateway_controller", return_value=controller),
			patch.object(type(pr), "create_payment_entry", new=_capture_builder_amount),
		):
			payment_core_utils.settle_payment_request(pr, controller=controller)
		payment_entry.captured_outstanding = captured[-1] if captured else None
		return payment_entry

	def test_second_partial_payment_settles_outstanding(self):
		"""40 then 60 on a 100 request: the second charge books the remaining
		outstanding and closes the PR - decisions must use outstanding_amount,
		not grand_total."""
		from frappe.utils import flt

		pr = self._make_single_currency_pr()

		first = self._settle(pr, 40.0)
		self.assertEqual(flt(first.captured_outstanding), 40.0)

		second = self._settle(pr, 60.0)
		self.assertEqual(flt(second.captured_outstanding), 60.0)

	def test_unknown_charge_books_outstanding(self):
		"""Provider reports nothing: book exactly the outstanding (ERPNext's
		own semantics), never the full grand_total again."""
		from frappe.utils import flt

		pr = self._make_single_currency_pr()
		self._settle(pr, 40.0)

		# unknown charge settles the full outstanding: the stored outstanding
		# reaches the builder untouched
		second = self._settle(pr, None)
		self.assertEqual(flt(second.captured_outstanding), flt(pr.outstanding_amount))

	def test_settle_books_flagged_sales_invoice(self):
		"""A request flagged make_sales_invoice gets its Sales Invoice booked
		after the Payment Entry, mirroring ERPNext's set_as_paid (shopping
		cart flow); an unflagged request never does."""
		pr = self._make_single_currency_pr()
		pr.db_set("make_sales_invoice", 1)

		with patch.object(pr, "make_invoice") as make_invoice:
			self._settle(pr, None)

		make_invoice.assert_called_once()

		plain = self._make_single_currency_pr()
		with patch.object(plain, "make_invoice") as make_invoice:
			self._settle(plain, None)

		make_invoice.assert_not_called()

	def test_partial_charge_books_only_what_was_charged(self):
		"""A real, unmocked partial settlement: a 40 charge on a 100 request
		must book paid_amount == received_amount == 40 with zero unallocated
		advance, and leave the request at outstanding 60 / Partially Paid.
		Lowering only allocated_amount on a full-outstanding PE would record
		100 in the bank and park 60 as an advance the buyer never paid."""
		from frappe.utils import flt

		pr = self._make_single_currency_pr()

		controller = MagicMock()
		controller.get_charged_amount = MagicMock(return_value=40.0)
		with patch("payment_core.utils.get_payment_gateway_controller", return_value=controller):
			payment_entry = payment_core_utils.settle_payment_request(pr, controller=controller)

		pe = frappe.get_doc("Payment Entry", payment_entry.name)
		self.assertEqual(flt(pe.paid_amount), 40.0)
		self.assertEqual(flt(pe.received_amount), 40.0)
		self.assertEqual(flt(pe.get_base_unallocated_amount()), 0.0)

		updated = frappe.db.get_value(
			"Payment Request", pr.name, ["status", "outstanding_amount"], as_dict=True
		)
		self.assertEqual(updated.status, "Partially Paid")
		self.assertEqual(flt(updated.outstanding_amount), 60.0)

	def test_settle_pays_only_the_request_the_buyer_paid(self):
		"""Two open Payment Requests on one Sales Order: settling the newer
		request must not touch the older one. A bare get_payment_entry would
		run ERPNext's open-request allocation and attach the OLDEST open
		request to the Payment Entry; building through
		pr.create_payment_entry (created_from_payment_request=True) allocates
		this request, and PE submit updates exactly it - and reverses it on
		PE cancel."""
		from frappe.utils import flt

		company, customer, item, company_currency = self._ensure_erpnext_fixtures()
		si = frappe.new_doc("Sales Invoice")
		si.customer = customer
		si.company = company
		si.currency = company_currency
		si.append("items", {"item_code": item, "qty": 1, "rate": 200})
		si.insert()
		si.submit()

		older = erpnext_payment_request.make_payment_request(
			dt="Sales Invoice", dn=si.name, recipient_id=None, payment_type="Outward", mute=1
		)
		if isinstance(older, dict):
			older = frappe.get_doc("Payment Request", older.get("name"))
		# request half the invoice so a second request fits beside it
		older.grand_total = 100
		older.outstanding_amount = 100
		older.flags.mute_email = 1
		with patch.object(older, "set_payment_request_url"):
			older.submit()

		# ERPNext refuses a second make_payment_request while one is open;
		# a second open request is exactly the scenario under test, so copy it
		newer = frappe.copy_doc(older)
		newer.docstatus = 0
		newer.name = None
		newer.flags.mute_email = 1
		newer.insert(ignore_permissions=True)
		with patch.object(newer, "set_payment_request_url"):
			newer.submit()
		self.assertNotEqual(older.name, newer.name, "expected two distinct open requests")

		controller = MagicMock()
		controller.get_charged_amount = MagicMock(return_value=None)  # unknown -> full outstanding
		with patch("payment_core.utils.get_payment_gateway_controller", return_value=controller):
			payment_entry = payment_core_utils.settle_payment_request(newer, controller=controller)

		self.assertIsNotNone(payment_entry)
		# the PE belongs to the request the buyer actually paid
		self.assertEqual(payment_entry.reference_no, newer.name)
		self.assertEqual(payment_entry.references[0].payment_request, newer.name)

		newer_row = frappe.db.get_value(
			"Payment Request", newer.name, ["status", "outstanding_amount"], as_dict=True
		)
		self.assertEqual(newer_row.status, "Paid")
		self.assertEqual(flt(newer_row.outstanding_amount), 0.0)

		# the older request stays exactly as it was
		older_row = frappe.db.get_value(
			"Payment Request", older.name, ["status", "outstanding_amount"], as_dict=True
		)
		self.assertEqual(older_row.status, "Requested")
		self.assertEqual(flt(older_row.outstanding_amount), flt(older.grand_total))

	def test_multi_currency_full_charge_books_builder_allocation(self):
		"""Full charges are not scaled by payment_core: ERPNext's own builder
		(the one that converts and fills dimensions) books the outstanding
		as-is, so payment_core must leave the allocation untouched."""
		from frappe.utils import flt

		pr = self._make_multi_currency_pr()

		payment_entry = self._settle(pr, flt(pr.outstanding_amount))

		self.assertEqual(flt(payment_entry.captured_outstanding), flt(pr.outstanding_amount))

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
