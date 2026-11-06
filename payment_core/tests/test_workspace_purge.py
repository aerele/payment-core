# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT
#
# Gateway-only workspace purge: rows pointing at purged ledger artifacts must
# be removed, and non-ledger rows must survive.

from unittest import skipUnless

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.ledger_gate import _purge_workspace_ledger_links
from payment_core.mode import is_gateway_only

WORKSPACE = "Payment Core"


@skipUnless(is_gateway_only(), "workspace purge runs on gateway-only sites")
class TestWorkspaceLedgerPurge(FrappeTestCase):
	def setUp(self):
		self.workspace_exists = frappe.db.exists("Workspace", WORKSPACE)
		if not self.workspace_exists:
			self.skipTest("Payment Core workspace not installed")

	def _make_link(self, label, link_type, link_to):
		row = frappe.new_doc("Workspace Link")
		row.update(
			{
				"parent": WORKSPACE,
				"parenttype": "Workspace",
				"parentfield": "links",
				"label": label,
				"link_type": link_type,
				"link_to": link_to,
				"type": "Link",
			}
		)
		row.flags.ignore_links = True
		row.insert(ignore_permissions=True)
		return row.name

	def _make_shortcut(self, label, link_type, link_to):
		row = frappe.new_doc("Workspace Shortcut")
		row.update(
			{
				"parent": WORKSPACE,
				"parenttype": "Workspace",
				"parentfield": "shortcuts",
				"label": label,
				"type": link_type,
				"link_to": link_to,
				"color": "Grey",
			}
		)
		row.flags.ignore_links = True
		row.insert(ignore_permissions=True)
		return row.name

	def test_ledger_rows_removed_and_non_ledger_rows_survive(self):
		from payment_core.mode import LEDGER_DOCTYPES, LEDGER_PAGE, LEDGER_REPORT

		ledger_doctype = LEDGER_DOCTYPES[0]

		ledger_link = self._make_link("Ledger Link", "DocType", ledger_doctype)
		page_link = self._make_link("Builder Link", "Page", LEDGER_PAGE)
		report_link = self._make_link("Report Link", "Report", LEDGER_REPORT)
		keeper_link = self._make_link("Keeper Link", "DocType", "Payment Gateway")

		ledger_shortcut = self._make_shortcut("Ledger Shortcut", "DocType", ledger_doctype)
		page_shortcut = self._make_shortcut("Builder Shortcut", "Page", LEDGER_PAGE)
		report_shortcut = self._make_shortcut("Report Shortcut", "Report", LEDGER_REPORT)
		keeper_shortcut = self._make_shortcut("Keeper Shortcut", "Page", "gateway-settings")

		# db_insert, not insert(): the card references a doctype that does not
		# exist on this site (that's the point), and the controller's validate
		# would call get_meta on it
		card = frappe.new_doc("Number Card")
		card.update(
			{
				"label": "PC Purge Card",
				"document_type": ledger_doctype,
				"function": "Count",
				"type": "Document Type",
				"is_public": 1,
			}
		)
		card.name = frappe.generate_hash("PC Purge Card", 10)
		card.db_insert()
		card_ref = frappe.new_doc("Workspace Number Card")
		card_ref.update(
			{
				"parent": WORKSPACE,
				"parenttype": "Workspace",
				"parentfield": "number_cards",
				"label": "PC Purge Card",
				"number_card_name": card.name,
			}
		)
		card_ref.insert(ignore_permissions=True)

		_purge_workspace_ledger_links()

		for name, doctype in (
			(ledger_link, "Workspace Link"),
			(page_link, "Workspace Link"),
			(report_link, "Workspace Link"),
			(ledger_shortcut, "Workspace Shortcut"),
			(page_shortcut, "Workspace Shortcut"),
			(report_shortcut, "Workspace Shortcut"),
			(card_ref.name, "Workspace Number Card"),
			(card.name, "Number Card"),
		):
			self.assertFalse(frappe.db.exists(doctype, name), f"{doctype} {name} survived the purge")

		self.assertTrue(frappe.db.exists("Workspace Link", keeper_link))
		self.assertTrue(frappe.db.exists("Workspace Shortcut", keeper_shortcut))

	def test_payment_ledger_section_stripped_from_home(self):
		"""The home's 'Payment Ledger' shortcut section (content blocks with a
		payment-ledger- id) references ledger shortcuts; on gateway-only sites
		the purge must remove the section, not leave orphan blocks."""
		from payment_core.mode import LEDGER_REPORT

		self._make_shortcut("Payment Settlement Summary", "Report", LEDGER_REPORT)
		blocks = [
			{"id": "payment-core-header", "type": "header"},
			{"id": "payment-analytics-block", "type": "custom_block"},
			{"id": "payment-ledger-header", "type": "header"},
			{"id": "payment-ledger-report", "type": "shortcut"},
		]
		frappe.db.set_value("Workspace", WORKSPACE, "content", frappe.as_json(blocks), update_modified=False)

		_purge_workspace_ledger_links()

		kept = frappe.parse_json(frappe.db.get_value("Workspace", WORKSPACE, "content"))
		self.assertEqual(
			[block["id"] for block in kept],
			["payment-core-header", "payment-analytics-block"],
		)

	def test_standard_sidebar_ledger_items_purged(self):
		"""The curated standard Sidebar ships ledger items; on gateway-only
		sites the purge removes them (and section breaks left empty), keeping
		the curated order for everything that does exist."""
		from payment_core.mode import LEDGER_DOCTYPES, LEDGER_PAGE

		if not (frappe.db.exists("DocType", "Sidebar") and frappe.db.exists("Sidebar", "Payment Core")):
			self.skipTest("standard Sidebar not installed on this Frappe version")

		def _add_item(label, item_type, link_type, link_to, child=0):
			row = frappe.new_doc("Sidebar Item")
			row.update(
				{
					"parent": "Payment Core",
					"parenttype": "Sidebar",
					"parentfield": "items",
					"label": label,
					"type": item_type,
					"link_type": link_type,
					"link_to": link_to,
					"child": child,
				}
			)
			row.flags.ignore_links = True
			row.insert(ignore_permissions=True)
			return row.name

		ledger_item = _add_item("Ledger Item", "Link", "DocType", LEDGER_DOCTYPES[0])
		builder_item = _add_item("Builder Item", "Link", "Page", LEDGER_PAGE)
		keeper_item = _add_item("Keeper Item", "Link", "DocType", "Payment Gateway")

		_purge_workspace_ledger_links()

		self.assertFalse(frappe.db.exists("Sidebar Item", ledger_item))
		self.assertFalse(frappe.db.exists("Sidebar Item", builder_item))
		self.assertTrue(frappe.db.exists("Sidebar Item", keeper_item))

		labels = frappe.get_all(
			"Sidebar Item", filters={"parent": "Payment Core", "parenttype": "Sidebar"}, pluck="label"
		)
		# the shipped fixture's ledger entries are gone on gateway-only sites
		self.assertNotIn("Payment Transaction", labels)
		self.assertNotIn("Payment Settlement Summary", labels)
		self.assertIn("Payment Gateway", labels)

	def test_ledger_dashboard_chart_removed(self):
		from payment_core.mode import LEDGER_DOCTYPES

		# db_insert for the same reason as the number card: validate would
		# resolve the missing doctype's meta
		chart = frappe.new_doc("Dashboard Chart")
		chart.update(
			{
				"chart_name": frappe.generate_hash("PC Purge Chart", 8),
				"chart_type": "Count",
				"document_type": LEDGER_DOCTYPES[0],
				"type": "Line",
				"is_public": 1,
			}
		)
		chart.name = chart.chart_name
		chart.db_insert()

		_purge_workspace_ledger_links()

		self.assertFalse(frappe.db.exists("Dashboard Chart", chart.name))
