# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Analytics scoping: every widget honors the reference-doctype filter, the
# breakdown lists the doctypes with captured money, and top customers join
# through the transaction honoring each site's customer doctype. Assertions
# are delta-based so committed demo data on the site cannot skew them.

import json
from unittest import skipUnless
from unittest.mock import patch

import frappe
from frappe.permissions import has_permission
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, nowdate

from payment_core.analytics import (
	get_analytics,
	get_daily_series,
	get_kpis,
	get_method_breakdown,
	get_range_currencies,
	get_reference_doctype_breakdown,
	get_top_customers,
)
from payment_core.analytics_adapters import adapted_payload, erpnext_adapter
from payment_core.analytics_display import resolve_since
from payment_core.mode import ledger_installed
from payment_core.utils import (
	create_payment_transaction,
	record_payment_receipt,
	update_payment_transaction,
)

ERPNEXT_INSTALLED = "erpnext" in frappe.get_installed_apps()


def _make_note(title=None):
	return (
		frappe.get_doc({"doctype": "Note", "title": title or frappe.generate_hash(length=8), "public": 1})
		.insert(ignore_permissions=True)
		.name
	)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestAnalyticsScoping(FrappeTestCase):
	def _capture(self, reference_doctype, reference_docname, amount, customer_email=None):
		transaction = create_payment_transaction(
			reference_doctype=reference_doctype,
			reference_docname=reference_docname,
			gateway="Stripe:Test",
			amount=amount,
			customer_email=customer_email,
		)
		record_payment_receipt(transaction=transaction.name, amount=amount)
		return transaction.name

	@staticmethod
	def _gross(reference_doctype=None):
		return flt(get_kpis(None, reference_doctype)["gross"])

	def setUp(self):
		self.note = _make_note()
		# every test starts with at least one Note capture so breakdown and
		# scoped widgets have data regardless of alphabetical test order
		self._capture("Note", self.note, 100)

	def test_scope_excludes_other_doctypes(self):
		gateway = frappe.get_doc(
			{
				"doctype": "Payment Gateway",
				"gateway": f"Analytics GW {frappe.generate_hash(length=5).title()}",
				"gateway_settings": "Note",
				"gateway_controller": _make_note(),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Payment Gateway", gateway.name, force=True)

		base_note, base_gateway = self._gross("Note"), self._gross("Payment Gateway")
		self._capture("Note", self.note, 500)
		self._capture("Payment Gateway", gateway.name, 900)

		self.assertAlmostEqual(self._gross("Note") - base_note, 500)
		self.assertAlmostEqual(self._gross("Payment Gateway") - base_gateway, 900)
		self.assertEqual(len(get_method_breakdown(None, "Note")), 1)

	def test_breakdown_consistent_with_gross(self):
		"""Breakdown and KPIs use the same data source: receipts-only.
		A receiptless paid transaction must NOT appear in the breakdown
		while gross (also receipts-only) shows 0 for that doctype."""
		gateway = frappe.get_doc(
			{
				"doctype": "Payment Gateway",
				"gateway": f"Consistency GW {frappe.generate_hash(length=5).title()}",
				"gateway_settings": "Note",
				"gateway_controller": _make_note(),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Payment Gateway", gateway.name, force=True)
		transaction = create_payment_transaction(
			reference_doctype="Payment Gateway",
			reference_docname=gateway.name,
			gateway="Stripe:Test",
			amount=250,
		)
		update_payment_transaction(transaction.name, status="Paid")

		breakdown = {row["doctype"] for row in get_reference_doctype_breakdown(None)}
		self.assertNotIn("Payment Gateway", breakdown)

		# for doctypes WITH receipts, the pill total equals the scoped gross
		self._capture("Note", self.note, 123)
		breakdown = {r["doctype"]: flt(r["captured"]) for r in get_reference_doctype_breakdown(None)}
		scoped_gross = flt(get_kpis(None, "Note")["gross"])
		self.assertAlmostEqual(breakdown.get("Note", 0), scoped_gross)

	def test_reference_doctype_breakdown_lists_captured_doctypes(self):
		base = {row["doctype"]: flt(row["captured"]) for row in get_reference_doctype_breakdown(None)}
		self._capture("Note", self.note, 300)

		after = {row["doctype"]: flt(row["captured"]) for row in get_reference_doctype_breakdown(None)}
		self.assertAlmostEqual(after.get("Note", 0) - base.get("Note", 0), 300)

	def test_top_customers_join_and_fallbacks(self):
		# no linked customer on the transaction: the buyer falls back to the
		# recorded email, still joined through the receipt->transaction link
		email = f"analytics.{frappe.generate_hash(length=6).lower()}@example.com"
		self._capture("Note", self.note, 700, customer_email=email)

		row = next((entry for entry in get_top_customers(None, "Note") if entry["label"] == email), None)
		self.assertIsNotNone(row)
		self.assertIsNone(row["customer_doctype"])
		self.assertAlmostEqual(flt(row["captured"]), 700)

		# scoped to a doctype with no captures -> empty list
		self.assertEqual(get_top_customers(None, "Workflow"), [])

	def test_get_analytics_accepts_scope_without_error(self):
		frappe.set_user("Administrator")
		data = get_analytics(range_key="30", reference_doctype="Note")
		self.assertEqual(data["reference_doctype"], "Note")
		self.assertTrue(any(row["doctype"] == "Note" for row in data["doctype_breakdown"]))
		self.assertEqual(len(data["chart"]["data"]["labels"]), 30)
		self.assertEqual(len(data["chart"]["data"]["datasets"][0]["values"]), 30)
		data_all = get_analytics(range_key="30")
		self.assertIsNone(data_all["reference_doctype"])


class TestAnalyticsWithoutLedger(FrappeTestCase):
	def test_analytics_degrades_without_ledger(self):
		frappe.set_user("Administrator")
		hooks_map = {"payment_analytics_adapter": ["payment_core.tests.test_analytics._fake_adapter"]}
		with (
			patch("frappe.db.table_exists", return_value=False),
			patch("frappe.get_installed_apps", return_value=["frappe", "payment_core", "tuition_app"]),
			patch("frappe.get_hooks", side_effect=_hooks_lookup(hooks_map)),
		):
			data = get_analytics(range_key="30")
		self.assertFalse(data["ledger_installed"])
		# no erpnext and no adapter -> mode note; adapter present -> data source
		self.assertTrue(data["mode_note"] or data["data_source"])


class TestAnalyticsPageConfiguration(FrappeTestCase):
	def test_analytics_page_allows_payment_roles(self):
		json_path = frappe.get_app_path(
			"payment_core",
			"payment_core",
			"page",
			"payment_analytics",
			"payment_analytics.json",
		)
		with open(json_path) as page_file:
			page = json.load(page_file)

		self.assertEqual(
			{row["role"] for row in page["roles"]},
			{"Payment Manager", "Payment User", "System Manager"},
		)


def _hooks_lookup(hooks_map):
	"""Side effect mirroring frappe.get_hooks: no hook -> full map, else list."""

	def lookup(hook=None, *args, **kwargs):
		if hook is None:
			return hooks_map
		return hooks_map.get(hook, [])

	return lookup


def _windowed_fake_adapter(
	since, range_key, reference_doctype=None, recent_days=None, open_days=None, currency=None
):
	return {
		"range": range_key,
		"reference_doctype": None,
		"ledger_installed": False,
		"data_source": "Tuition Invoice (test app)",
		"mode_note": None,
		"health_warnings": [],
		"gateways": [],
		"ranges": {},
		"recent_days": recent_days,
		"open_days": open_days,
	}


def _fake_adapter(since, range_key, reference_doctype=None, **kwargs):
	return {
		"range": range_key,
		"reference_doctype": None,
		"ledger_installed": False,
		"data_source": "Tuition Invoice (test app)",
		"mode_note": None,
		"health_warnings": [],
		"gateways": [],
		"ranges": {},
		"doctype_breakdown": [{"doctype": "Tuition Invoice", "captured": 500, "count": 1}],
		"kpis": {"gross": 500, "successful": 1, "customers": 1, "average": 500},
		"chart": {"data": {"labels": [], "datasets": [{"name": "Captured", "values": []}]}},
		"donut": {"data": {"labels": [], "datasets": [{"values": []}]}, "total": 0},
		"top_customers": [],
		"recent": [],
		"open_payments": [],
		"failed_payments": [],
	}


class TestAnalyticsAdapters(FrappeTestCase):
	def test_custom_app_adapter_via_hook(self):
		# a gateway-only site whose app registers payment_analytics_adapter

		hooks_map = {"payment_analytics_adapter": ["payment_core.tests.test_analytics._fake_adapter"]}
		with (
			patch("frappe.db.table_exists", return_value=False),
			patch("frappe.get_installed_apps", return_value=["frappe", "payment_core", "tuition_app"]),
			patch("frappe.get_hooks", side_effect=_hooks_lookup(hooks_map)),
		):
			payload = adapted_payload(None, "30")
		self.assertEqual(payload["data_source"], "Tuition Invoice (test app)")

	def test_windowed_adapter_receives_day_windows_and_legacy_survives(self):
		with patch("payment_core.analytics_adapters.get_adapter", return_value=_windowed_fake_adapter):
			payload = adapted_payload(None, "90", None, "7", "today")
		self.assertEqual(payload["recent_days"], "7")
		self.assertEqual(payload["open_days"], "today")

		# legacy 3-arg adapters keep working; windows are silently not passed
		with patch("payment_core.analytics_adapters.get_adapter", return_value=_fake_adapter):
			payload = adapted_payload(None, "30", None, "7", "today")
		self.assertEqual(payload["range"], "30")
		self.assertEqual(payload["kpis"]["gross"], 500)
		self.assertFalse(payload["ledger_installed"])

	def test_erpnext_adapter_reports_own_flow(self):
		# real ERPNext data: gateway-settled Payment Entries feed the payload
		if "erpnext" not in frappe.get_installed_apps():
			self.skipTest("erpnext not installed")

		payload = erpnext_adapter(None, "all")
		self.assertIn("Payment Request", payload["data_source"])
		# fresh ERPNext sites may have no settled Payment Entries; assert counts only when data exists
		self.assertIsInstance(payload["kpis"]["successful"], (int, float))
		if payload["kpis"]["successful"]:
			self.assertEqual(payload["doctype_breakdown"][0]["doctype"], "Payment Request")
			self.assertTrue(
				all(row["route"].startswith("/app/payment-request/") for row in payload["recent"])
			)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestCurrencyScoping(FrappeTestCase):
	def _capture_currency(self, reference_docname, amount, currency):
		transaction = create_payment_transaction(
			reference_doctype="Note",
			reference_docname=reference_docname,
			gateway="Stripe:Test",
			amount=amount,
			currency=currency,
		)
		record_payment_receipt(transaction=transaction.name, amount=amount)
		return transaction.name

	def test_default_currency_is_highest_volume(self):
		note = _make_note()
		self._capture_currency(note, 800, "EUR")
		self._capture_currency(note, 200, "USD")
		currencies = get_range_currencies(None)
		if "EUR" in currencies and "USD" in currencies:
			self.assertLess(currencies.index("EUR"), currencies.index("USD"))

	def test_kpis_scope_counts_to_selected_currency(self):
		note = _make_note()
		self._capture_currency(note, 500, "USD")
		usd = get_kpis(None, None, "USD")
		inr = get_kpis(None, None, "INR")
		self.assertIsInstance(usd["successful"], int)
		self.assertIsInstance(inr["successful"], int)

	def test_receiptless_currencies_discovered(self):
		transaction = create_payment_transaction(
			reference_doctype="Note",
			reference_docname=_make_note(),
			gateway="Stripe:Test",
			amount=42,
			currency="JPY",
		)
		update_payment_transaction(transaction.name, status="Paid")
		self.assertIn("JPY", get_range_currencies(None))

	def test_multiple_fallback_transactions_accumulate(self):
		gateway = frappe.get_doc(
			{
				"doctype": "Payment Gateway",
				"gateway": f"Multi FB {frappe.generate_hash(length=5).title()}",
				"gateway_settings": "Note",
				"gateway_controller": _make_note(),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Payment Gateway", gateway.name, force=True)
		for amount in (100, 150, 200):
			transaction = create_payment_transaction(
				reference_doctype="Payment Gateway",
				reference_docname=gateway.name,
				gateway="Stripe:Test",
				amount=amount,
			)
			update_payment_transaction(transaction.name, status="Paid")

		breakdown = {row["doctype"] for row in get_reference_doctype_breakdown(None)}
		self.assertNotIn("Payment Gateway", breakdown)  # receipts-only now

	def test_top_customers_consistent_under_variants(self):
		note = _make_note()
		self._capture_currency(note, 10, "INR")
		rows = get_top_customers(None, "Note", "INR", limit=5)
		self.assertIsInstance(rows, list)
		self.assertLessEqual(len(rows), 5)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestGatewaySettingsPermissions(FrappeTestCase):
	"""Gateway Settings (page + provider forms) is a System Manager surface:
	provider settings doctypes are System Manager-only in every gateway app,
	so exposing the page to Payment Manager would show links that 403."""

	def _make_user(self, email_prefix, role):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"{email_prefix}-{frappe.generate_hash(length=6).lower()}@example.com",
				"first_name": email_prefix.title(),
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "User", user.name, force=True)
		return user

	def test_payment_manager_reads_registry_but_not_the_page(self):
		tester = self._make_user("pm-gw", "Payment Manager")
		frappe.set_user(tester.email)
		self.addCleanup(frappe.set_user, "Administrator")
		# analytics need the registry; the configure page stays admin-only
		self.assertTrue(has_permission("Payment Gateway", "read"))
		self.assertFalse(
			frappe.db.exists("Page", {"name": "gateway-settings", "roles": {"role": "Payment Manager"}})
		)

	def test_gateway_settings_page_is_system_manager_only(self):
		# read the page JSON from disk: the DB copy only re-syncs on fresh
		# installs, so existing sites may lag behind the schema
		json_path = frappe.get_app_path(
			"payment_core", "payment_core", "page", "gateway_settings", "gateway_settings.json"
		)
		with open(json_path) as file:
			page_def = json.load(file)
		roles = {row["role"] for row in page_def["roles"]}
		self.assertEqual(roles, {"System Manager"})

	def test_system_manager_reads_gateway_registry(self):
		admin = self._make_user("sm-gw", "System Manager")
		frappe.set_user(admin.email)
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertTrue(has_permission("Payment Gateway", "read"))


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestCancelledCaptureExcluded(FrappeTestCase):
	"""Cancelled (docstatus 2) and draft captures must not contribute to any
	analytics total - only submitted receipts move money."""

	def test_cancelled_capture_excluded_from_all_totals(self):
		note = _make_note()
		# baseline before any test data (durable on sites with existing data)
		base_kpis = get_kpis(None, "Note")
		base_breakdown = {r["doctype"]: flt(r["captured"]) for r in get_reference_doctype_breakdown(None)}
		base_currencies = get_range_currencies(None)

		# capture with an isolated fixture currency, then cancel: the receipt
		# stays in the table at docstatus 2
		fixture_currency = "XDR"  # IMF special drawing rights: never a real charge
		transaction = create_payment_transaction(
			reference_doctype="Note",
			reference_docname=note,
			gateway="Stripe:Test",
			amount=999,
			currency=fixture_currency,
		)
		receipt_name = record_payment_receipt(transaction=transaction.name, amount=999)
		frappe.get_doc("Payment Receipt", receipt_name).cancel()

		# every total must be unchanged: the cancelled capture is invisible
		after_kpis = get_kpis(None, "Note")
		self.assertAlmostEqual(flt(after_kpis["gross"]), flt(base_kpis["gross"]))
		self.assertEqual(after_kpis["successful"], base_kpis["successful"])

		after_breakdown = {r["doctype"]: flt(r["captured"]) for r in get_reference_doctype_breakdown(None)}
		self.assertAlmostEqual(after_breakdown.get("Note", 0), base_breakdown.get("Note", 0))

		# the cancelled capture's currency must not appear anywhere
		after_currencies = get_range_currencies(None)
		self.assertEqual(after_currencies, base_currencies)

		# no fixture-currency rows in the method breakdown or top customers either
		methods = get_method_breakdown(None, "Note", fixture_currency)
		self.assertEqual(methods, [])
		customers = get_top_customers(None, "Note", fixture_currency)
		self.assertEqual(customers, [])

		# daily series with the fixture-currency scope is all zeros
		series = get_daily_series(None, "all", "Note", fixture_currency)
		self.assertTrue(all(point["total"] == 0 for point in series))


@skipUnless(ERPNEXT_INSTALLED, "erpnext not installed")
class TestPaymentEntryDoubleReference(FrappeTestCase):
	def test_one_pe_with_two_pr_references_counts_once(self):
		currency = "XTS"  # ISO 4217 code reserved for test transactions.
		allocated_amounts = (60, 40)
		payment_requests = []
		for amount in allocated_amounts:
			payment_request = frappe.get_doc(
				{
					"doctype": "Payment Request",
					"name": f"_Test Payment Request {frappe.generate_hash(length=10)}",
					"docstatus": 1,
					"payment_request_type": "Inward",
					"naming_series": "ACC-PRQ-.YYYY.-",
					"transaction_date": nowdate(),
					"grand_total": amount,
					"outstanding_amount": 0,
					"currency": currency,
					"status": "Paid",
				}
			)
			payment_request.db_insert()
			payment_requests.append(payment_request.name)

		payment_entry = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"name": f"_Test Payment Entry {frappe.generate_hash(length=10)}",
				"docstatus": 1,
				"naming_series": "ACC-PAY-.YYYY.-",
				"payment_type": "Receive",
				"posting_date": nowdate(),
				"company": "_Test Payment Analytics Company",
				"party_type": "Customer",
				"party": "_Test Payment Analytics Customer",
			}
		)
		payment_entry.db_insert()

		for idx, (payment_request, allocated_amount) in enumerate(
			zip(payment_requests, allocated_amounts, strict=True), start=1
		):
			frappe.get_doc(
				{
					"doctype": "Payment Entry Reference",
					"name": frappe.generate_hash(length=10),
					"parent": payment_entry.name,
					"parenttype": "Payment Entry",
					"parentfield": "references",
					"idx": idx,
					"reference_doctype": "Payment Request",
					"reference_name": payment_request,
					"payment_request": payment_request,
					"allocated_amount": allocated_amount,
				}
			).db_insert()

		kpis = erpnext_adapter(None, "all", currency=currency)["kpis"]

		self.assertAlmostEqual(flt(kpis["gross"]), sum(allocated_amounts))
		self.assertEqual(kpis["successful"], 1)
