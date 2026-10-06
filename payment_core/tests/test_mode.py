# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Gateway-only mode: detection, suppression, purge and guarded gateway paths.

from unittest import skipUnless
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.ledger_gate import suppress_ledger_module
from payment_core.mode import is_gateway_only, ledger_installed


def _with_apps(*apps):
	return patch("frappe.get_installed_apps", return_value=list(apps))


class TestGatewayOnlyMode(FrappeTestCase):
	def test_ledger_site_reports_not_gateway_only(self):
		# spares-style site: no erpnext, no own-flow declaration
		with _with_apps("frappe", "payment_core", "spare_parts"):
			with patch("frappe.get_hooks", return_value={}):
				self.assertFalse(is_gateway_only())

	def test_erpnext_forces_gateway_only(self):
		with _with_apps("frappe", "erpnext", "payment_core"):
			self.assertTrue(is_gateway_only())

	def test_own_flow_hook_forces_gateway_only(self):
		with _with_apps("frappe", "payment_core", "lms_app"):
			with patch("frappe.get_hooks", return_value={"uses_own_payment_flow": ["lms_app.hooks"]}):
				self.assertTrue(is_gateway_only())

	def test_force_payment_ledger_overrides(self):
		frappe.conf.force_payment_ledger = 1
		self.addCleanup(frappe.conf.pop, "force_payment_ledger", None)
		with _with_apps("frappe", "erpnext", "payment_core"):
			self.assertFalse(is_gateway_only())

	def test_suppress_removes_ledger_module_on_gateway_only_sites(self):
		modules = frappe.local.app_modules.setdefault("payment_core", [])
		if "payment_ledger" not in modules:
			modules.append("payment_ledger")
		with _with_apps("frappe", "erpnext", "payment_core"):
			suppress_ledger_module()
		self.assertNotIn("payment_ledger", frappe.local.app_modules["payment_core"])

	def test_suppress_noop_on_ledger_sites(self):
		modules = frappe.local.app_modules.setdefault("payment_core", [])
		if "payment_ledger" not in modules:
			modules.append("payment_ledger")
		with _with_apps("frappe", "payment_core", "spare_parts"):
			with patch("frappe.get_hooks", return_value={}):
				suppress_ledger_module()
		self.assertIn("payment_ledger", frappe.local.app_modules["payment_core"])


STRIPE_INSTALLED = True
try:
	from stripe_payment.gateway.references import ensure_payment_transaction
except ImportError:
	STRIPE_INSTALLED = False


@skipUnless(STRIPE_INSTALLED, "stripe_payment not installed on this bench")
class TestGuardedGatewayPaths(FrappeTestCase):
	def test_ensure_payment_transaction_skips_without_table(self):
		data = frappe._dict({"reference_doctype": "Note", "reference_docname": "N1"})
		with patch("frappe.db.table_exists", return_value=False):
			self.assertIsNone(ensure_payment_transaction(None, data))
		self.assertNotIn("payment_transaction", data)

	def test_reconcile_status_returns_empty_without_ledger(self):
		from payment_core.utils import reconcile_payment_status

		with patch("frappe.db.table_exists", return_value=False):
			self.assertEqual(reconcile_payment_status("Note", "whatever"), "")

	def test_ledger_installed_reflects_site(self):
		self.assertEqual(ledger_installed(), frappe.db.table_exists("Payment Transaction"))
