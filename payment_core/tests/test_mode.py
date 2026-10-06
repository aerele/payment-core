# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Gateway-only mode: detection, suppression and the purge data guard.

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.ledger_gate import (
	_raise_on_non_empty_ledger,
	purge_ledger,
	suppress_ledger_module,
)
from payment_core.mode import (
	LEDGER_DOCTYPES,
	LEDGER_PAGE,
	LEDGER_REPORT,
	gateway_only_reason,
	is_gateway_only,
	ledger_installed,
)

GATE = "payment_core.ledger_gate"


def _with_apps(*apps):
	return patch("frappe.get_installed_apps", return_value=list(apps))


def _hooks_returning(value):
	# frappe.get_hooks("<hook>") returns the list of declared values
	return patch("frappe.get_hooks", return_value=value)


def _fresh_install_tables():
	# no ledger tables anywhere: the data guard sees nothing to protect
	return patch("frappe.db.table_exists", return_value=False)


class TestGatewayOnlyMode(FrappeTestCase):
	def test_ledger_site_reports_not_gateway_only(self):
		# spares-style site: no erpnext, no own-flow declaration
		with _with_apps("frappe", "payment_core", "spare_parts"):
			with _hooks_returning([]):
				self.assertFalse(is_gateway_only())
				self.assertIsNone(gateway_only_reason())

	def test_erpnext_forces_gateway_only(self):
		with _with_apps("frappe", "erpnext", "payment_core"):
			self.assertTrue(is_gateway_only())

	def test_own_flow_hook_forces_gateway_only(self):
		def hooks(hook=None, app_name=None, *args, **kwargs):
			# only lms_app declares the hook truthfully
			return [True] if app_name == "lms_app" else []

		with _with_apps("frappe", "payment_core", "lms_app"):
			with patch("frappe.get_hooks", side_effect=hooks):
				self.assertTrue(is_gateway_only())
				self.assertEqual(gateway_only_reason(), "App with its own payment flow installed: lms_app")

	def test_own_flow_false_does_not_force_gateway_only(self):
		# get_hooks returns values, not keys: [False] is not a declaration
		with _with_apps("frappe", "payment_core", "lms_app"):
			with _hooks_returning([False]):
				self.assertFalse(is_gateway_only())
				self.assertIsNone(gateway_only_reason())

	def test_force_payment_ledger_overrides(self):
		frappe.conf.force_payment_ledger = 1
		self.addCleanup(frappe.conf.pop, "force_payment_ledger", None)
		with _with_apps("frappe", "erpnext", "payment_core"):
			self.assertFalse(is_gateway_only())

	def test_ledger_installed_reflects_site(self):
		self.assertEqual(ledger_installed(), frappe.db.table_exists("Payment Transaction"))


class TestSuppressLedgerModule(FrappeTestCase):
	def _with_ledger_module(self):
		modules = frappe.local.app_modules.setdefault("payment_core", [])
		had_module = "payment_ledger" in modules
		if not had_module:
			modules.append("payment_ledger")

		def _restore():
			# return to exactly the pre-test state, whether or not suppress ran
			if had_module:
				if "payment_ledger" not in modules:
					modules.append("payment_ledger")
			elif "payment_ledger" in modules:
				modules.remove("payment_ledger")

		self.addCleanup(_restore)
		return modules

	def test_removes_ledger_module_on_gateway_only_sites(self):
		modules = self._with_ledger_module()
		with _with_apps("frappe", "erpnext", "payment_core"):
			with _fresh_install_tables():
				suppress_ledger_module()
		self.assertNotIn("payment_ledger", modules)

	def test_noop_on_ledger_sites(self):
		modules = self._with_ledger_module()
		with _with_apps("frappe", "payment_core", "spare_parts"):
			with _hooks_returning([]):
				suppress_ledger_module()
		self.assertIn("payment_ledger", modules)

	def test_blocks_instead_of_suppressing_when_data_exists(self):
		self._with_ledger_module()
		with (
			_with_apps("frappe", "erpnext", "payment_core"),
			patch("frappe.db.table_exists", return_value=True),
			patch("frappe.db.count", return_value=3),
		):
			with self.assertRaises(frappe.ValidationError):
				suppress_ledger_module()


class TestPurgeDataGuard(FrappeTestCase):
	def test_missing_tables_mean_empty(self):
		with _fresh_install_tables():
			self.assertIsNone(_raise_on_non_empty_ledger())

	def test_data_blocks_the_purge(self):
		with (
			patch("frappe.db.table_exists", return_value=True),
			patch("frappe.db.count", return_value=5),
		):
			with self.assertRaises(frappe.ValidationError):
				_raise_on_non_empty_ledger()

	def test_other_db_errors_re_raise(self):
		# a broken count must never read as "empty": that would drop a full table
		with (
			patch("frappe.db.table_exists", return_value=True),
			patch("frappe.db.count", side_effect=RuntimeError("connection lost")),
			patch("frappe.db.is_table_missing", return_value=False),
		):
			with self.assertRaises(RuntimeError):
				_raise_on_non_empty_ledger()


class TestPurgeLedger(FrappeTestCase):
	def test_removes_ledger_artifacts(self):
		def exists(doctype, name):
			return doctype in ("DocType", "Report", "Page")

		deleted = []
		with (
			patch(f"{GATE}.is_gateway_only", return_value=True),
			patch(f"{GATE}._raise_on_non_empty_ledger") as guard,
			patch("frappe.db.exists", side_effect=exists),
			_fresh_install_tables(),
			patch("frappe.delete_doc", side_effect=lambda dt, name, **kw: deleted.append((dt, name))),
			patch("frappe.get_all", return_value=[]),
		):
			purge_ledger()

		guard.assert_called_once()
		self.assertEqual({name for _, name in deleted}, set(LEDGER_DOCTYPES) | {LEDGER_REPORT, LEDGER_PAGE})

	def test_noop_on_ledger_sites(self):
		with (
			patch(f"{GATE}.is_gateway_only", return_value=False),
			patch("frappe.delete_doc") as delete_doc,
		):
			purge_ledger()
		delete_doc.assert_not_called()
