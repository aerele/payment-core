# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Boot policy: advertise mapped doctypes for the desk payment action.

from unittest import skipUnless

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.boot import extend_bootinfo
from payment_core.mode import ledger_installed


class TestBootPaymentPolicy(FrappeTestCase):
	def test_guest_boot_gets_no_payment_doctypes(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		bootinfo = frappe._dict()

		extend_bootinfo(bootinfo)

		self.assertEqual(bootinfo.payment_reference_doctypes, [])

	@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
	def test_mapped_doctypes_are_advertised(self):
		mapping = frappe.get_doc(
			{
				"doctype": "Payment Field Mapping",
				"reference_doctype": "Note",
				"mapping": [{"purpose": "amount", "reference_field": "title"}],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.db.delete,
			"Payment Field Mapping Item",
			{"parenttype": "Payment Field Mapping", "parent": mapping.name},
		)
		self.addCleanup(frappe.db.delete, "Payment Field Mapping", {"name": mapping.name})
		bootinfo = frappe._dict()

		extend_bootinfo(bootinfo)

		self.assertIn("Note", bootinfo.payment_reference_doctypes)
