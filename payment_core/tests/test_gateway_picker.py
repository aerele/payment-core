# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# The "Add Gateway" picker endpoint: gateway types come from the
# payment_gateway_settings_doctypes hook plus the Payment Gateway registry,
# deduped and existence-filtered, so gateway accounts are created through
# their settings form (which registers the Payment Gateway row itself)
# instead of hand-built duplicates.

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.workspace import get_gateway_settings_options

MODULE = "payment_core.workspace"


def _type_map(names, singles=()):
	return {name: name in singles for name in names}


class TestGatewaySettingsOptions(FrappeTestCase):
	def test_requires_gateway_read_permission(self):
		with patch.object(frappe, "has_permission", side_effect=frappe.PermissionError):
			self.assertRaises(frappe.PermissionError, get_gateway_settings_options)

	def test_merges_hook_and_registry_deduped_and_sorted(self):
		hooks = ["Stripe Settings", "Ghost Settings"]
		# the batch query sees only the real doctypes (Ghost Settings absent)
		with (
			patch(f"{MODULE}.frappe.has_permission"),
			patch(f"{MODULE}.frappe.get_hooks", return_value=hooks),
			patch(f"{MODULE}.frappe.get_all", return_value=["Stripe Settings", "Razorpay Settings"]),
			patch(
				f"{MODULE}._lookup_doctype_info",
				return_value=_type_map(["Stripe Settings", "Razorpay Settings"]),
			),
		):
			options = get_gateway_settings_options()

		labels = [option["label"] for option in options]
		self.assertEqual(labels, ["Razorpay Settings", "Stripe Settings"])  # deduped + sorted
		ghost = [option for option in options if option["label"] == "Ghost Settings"]
		self.assertFalse(ghost)  # uninstalled doctypes are filtered out

	def test_routes_follow_desk_slug_and_single_shape(self):
		hooks = ["Stripe Settings", "Flat Settings"]
		with (
			patch(f"{MODULE}.frappe.has_permission"),
			patch(f"{MODULE}.frappe.get_hooks", return_value=hooks),
			patch(f"{MODULE}.frappe.get_all", return_value=[]),
			patch(
				f"{MODULE}._lookup_doctype_info", return_value=_type_map(hooks, singles=("Flat Settings",))
			),
		):
			options = {option["label"]: option["route"] for option in get_gateway_settings_options()}
		self.assertEqual(options["Stripe Settings"], "/app/stripe-settings/new")
		self.assertEqual(options["Flat Settings"], "/app/flat-settings")  # Single: no /new

	def test_stripe_payment_declares_its_settings_doctype(self):
		declared = frappe.get_hooks("payment_gateway_settings_doctypes") or []
		if "stripe_payment" in frappe.get_installed_apps():
			self.assertIn("Stripe Settings", declared)
