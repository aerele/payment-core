# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT
#
# Auto-created Mode of Payment per gateway: creation on Payment Gateway
# Account insert, multi-company appends, the first-row-wins rule for a
# second currency, non-Bank account skip, and the enabled check. The
# Payment Request -> Payment Entry flow lives in
# test_payment_request_override.test_settle_stamps_gateway_mode_of_payment.

from unittest import skipUnless

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.mode_of_payment import (
	get_mode_of_payment_for_gateway,
	sync_for_gateway_account,
)

ERPNext_INSTALLED = frappe.db.exists("DocType", "Payment Request")


@skipUnless(ERPNext_INSTALLED, "Mode of Payment is an ERPNext feature")
class TestGatewayModeOfPayment(FrappeTestCase):
	def _ensure_company(self, name, abbr):
		# a fresh CI site lacks the setup-wizard's Warehouse Types; Company
		# on_update creates a Transit warehouse and would fail without this.
		# name set directly: Prompt autoname skips _prompt_autoname's throw
		if not frappe.db.exists("Warehouse Type", "Transit"):
			frappe.get_doc(
				{"doctype": "Warehouse Type", "warehouse_type": "Transit", "name": "Transit"}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Company", name):
			frappe.get_doc(
				{
					"doctype": "Company",
					"company_name": name,
					"abbr": abbr,
					"default_currency": "INR",
					"country": "India",
					"chart_of_accounts": "Standard",
				}
			).insert(ignore_permissions=True)
		return name

	def _bank_account(self, company, account_name, account_type="Bank", currency="INR"):
		abbr = frappe.db.get_value("Company", company, "abbr")
		if not frappe.db.exists("Account", account_name):
			parent = f"Bank Accounts - {abbr}" if account_type == "Bank" else f"Current Assets - {abbr}"
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": account_name.split(" - ")[0],
					"parent_account": parent,
					"company": company,
					"account_type": account_type,
					"account_currency": currency,
				}
			).insert(ignore_permissions=True)
		return account_name

	def _make_gateway(self, name=None):
		gateway = name or f"Stripe-Test-{frappe.generate_hash(length=4)}"
		if not frappe.db.exists("Payment Gateway", gateway):
			frappe.get_doc({"doctype": "Payment Gateway", "gateway": gateway}).insert(ignore_permissions=True)
		return gateway

	def _make_pga(self, gateway, company, account):
		return (
			frappe.get_doc(
				{
					"doctype": "Payment Gateway Account",
					"payment_gateway": gateway,
					"company": company,
					"payment_account": account,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_pga_insert_creates_mode_of_payment(self):
		company = self._ensure_company(
			f"_Test MOP {frappe.generate_hash(length=4)}", f"TM{frappe.generate_hash(length=2)}"
		)
		account = self._bank_account(
			company, f"Stripe Bank - {frappe.db.get_value('Company', company, 'abbr')}"
		)
		gateway = self._make_gateway()

		self._make_pga(gateway, company, account)

		# the MOP is named after the Payment Gateway (unique per gateway),
		# not after gateway_controller (which gateway apps set to the
		# settings row name — e.g. "GW-1" — and would collide)
		self.assertTrue(frappe.db.exists("Mode of Payment", gateway))
		mop = frappe.get_doc("Mode of Payment", gateway)
		self.assertEqual(mop.type, "Bank")
		self.assertEqual(mop.enabled, 1)
		rows = [r for r in mop.accounts if r.company == company]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].default_account, account)

	def test_second_currency_keeps_the_first_row(self):
		"""One gateway, one company, two currencies: the Mode of Payment
		allows a single account row per company, so the second PGA's account
		must NOT replace the row the first PGA created."""
		abbr = f"TC{frappe.generate_hash(length=2)}"
		company = self._ensure_company(f"_Test MOP TC {frappe.generate_hash(length=4)}", abbr)
		inr = self._bank_account(company, f"Bank First - {abbr}")
		usd = self._bank_account(company, f"Bank Second - {abbr}", currency="USD")
		gateway = self._make_gateway()

		self._make_pga(gateway, company, inr)
		# the autoname is gateway-currency-abbr, so a second PGA for the same
		# gateway+company needs its own currency to exist alongside
		pga2 = frappe.get_doc(
			{
				"doctype": "Payment Gateway Account",
				"payment_gateway": gateway,
				"company": company,
				"payment_account": usd,
				"currency": "USD",
			}
		).insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Payment Gateway Account", pga2.name))

		mop = frappe.get_doc("Mode of Payment", gateway)
		rows = [r for r in mop.accounts if r.company == company]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].default_account, inr)

	def test_second_company_appends_to_same_mop(self):
		abbr1 = f"M1{frappe.generate_hash(length=2)}"
		abbr2 = f"M2{frappe.generate_hash(length=2)}"
		company1 = self._ensure_company(f"_Test MOP A {frappe.generate_hash(length=4)}", abbr1)
		company2 = self._ensure_company(f"_Test MOP B {frappe.generate_hash(length=4)}", abbr2)
		account1 = self._bank_account(company1, f"Bank A - {abbr1}")
		account2 = self._bank_account(company2, f"Bank B - {abbr2}")
		gateway = self._make_gateway()

		self._make_pga(gateway, company1, account1)
		self._make_pga(gateway, company2, account2)

		mop = frappe.get_doc("Mode of Payment", gateway)
		companies = {r.company for r in mop.accounts}
		self.assertIn(company1, companies)
		self.assertIn(company2, companies)

	def test_account_change_follows_the_mop(self):
		"""Two gateways for one company each get their own MOP row; changing
		the payment account on the PGA updates the MOP row it created."""
		abbr = f"SC{frappe.generate_hash(length=2)}"
		company = self._ensure_company(f"_Test MOP SC {frappe.generate_hash(length=4)}", abbr)
		account1 = self._bank_account(company, f"Bank USD - {abbr}")
		account2 = self._bank_account(company, f"Bank INR - {abbr}")
		gateway1 = self._make_gateway()
		gateway2 = self._make_gateway()

		# same company, different gateways (the autoname is gateway-currency-abbr,
		# so same gateway + same currency would collide). Each creates its own
		# MOP; the "keep first" logic applies when the SAME gateway is saved
		# twice for the same company (below)
		self._make_pga(gateway1, company, account1)
		self._make_pga(gateway2, company, account2)

		mop1 = frappe.get_doc("Mode of Payment", gateway1)
		rows1 = [r for r in mop1.accounts if r.company == company]
		self.assertEqual(len(rows1), 1)
		self.assertEqual(rows1[0].default_account, account1)

		# re-saving the same gateway+company with a different account: the
		# hook knows the previous account (get_doc_before_save), so the
		# MOP row follows the change — that's the sync working correctly.
		# A different company or gateway would append instead.
		account3 = self._bank_account(company, f"Bank EUR - {abbr}")
		pga_name = frappe.db.get_value(
			"Payment Gateway Account", {"payment_gateway": gateway1, "company": company}
		)
		doc = frappe.get_doc("Payment Gateway Account", pga_name)
		doc.payment_account = account3
		# save() stores the before-save snapshot the sync needs, then fires
		# on_update which calls sync_for_gateway_account
		doc.save(ignore_permissions=True)

		mop = frappe.get_doc("Mode of Payment", gateway1)
		rows = [r for r in mop.accounts if r.company == company]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].default_account, account3)

	def test_non_bank_account_skips_mop(self):
		"""A clearing account (no type) is valid on the Payment Gateway
		Account but the Mode of Payment would reject it: the hook must
		skip, not block the Payment Gateway Account save."""
		abbr = f"CL{frappe.generate_hash(length=2)}"
		company = self._ensure_company(f"_Test MOP CL {frappe.generate_hash(length=4)}", abbr)
		clearing = self._bank_account(company, f"Stripe Clearing - {abbr}", account_type="")
		gateway = self._make_gateway()

		# must not throw
		pga = self._make_pga(gateway, company, clearing)
		self.assertTrue(frappe.db.exists("Payment Gateway Account", pga))
		self.assertFalse(frappe.db.exists("Mode of Payment", gateway))

	def test_disabled_mop_not_stamped(self):
		company = self._ensure_company(
			f"_Test MOP EN {frappe.generate_hash(length=4)}", f"EN{frappe.generate_hash(length=2)}"
		)
		account = self._bank_account(company, f"Bank EN - {frappe.db.get_value('Company', company, 'abbr')}")
		gateway = self._make_gateway()
		self._make_pga(gateway, company, account)

		frappe.db.set_value("Mode of Payment", gateway, "enabled", 0)
		self.assertIsNone(get_mode_of_payment_for_gateway(gateway))
