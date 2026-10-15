# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Contract tests for reference settlement dispatch on gateway-only sites:
# how an app with its own payment flow (ERPNext, LMS-style custom apps) gets
# paid without any payment_core ledger document. The dispatch order is
# duck-typed ``on_payment_authorized`` first, then the
# ``payment_reference_settlers`` hook, and the return value is always a
# redirect route (or None) — never a document.

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from frappe.tests.utils import FrappeTestCase

from payment_core.utils import authorize_reference

MODULE = "payment_core.utils"


class TestAuthorizeReferenceDispatch(FrappeTestCase):
	def test_duck_typed_on_payment_authorized_wins(self):
		ref = MagicMock()
		ref.doctype = "LMS Course Purchase"
		ref.name = "LMS-CP-0001"
		ref.run_method.return_value = "/lms/thanks"

		with patch(f"{MODULE}.frappe.get_doc", return_value=ref):
			result = authorize_reference("LMS Course Purchase", "LMS-CP-0001", "Paid")

		ref.run_method.assert_called_once_with("on_payment_authorized", "Paid")
		self.assertEqual(result, "/lms/thanks")

	def test_settler_hook_receives_reference_when_no_callback(self):
		ref = SimpleNamespace(doctype="LMS Course Purchase", name="LMS-CP-0002")
		handler = MagicMock(return_value="/lms/receipt")

		with (
			patch(f"{MODULE}.frappe.get_doc", return_value=ref),
			patch(f"{MODULE}.frappe.get_hooks", return_value={"LMS Course Purchase": ["fake_app.settle"]}),
			patch(f"{MODULE}.frappe.get_attr", return_value=handler),
		):
			result = authorize_reference("LMS Course Purchase", "LMS-CP-0002", "Paid")

		handler.assert_called_once_with(ref)
		self.assertEqual(result, "/lms/receipt")

	def test_every_registered_settler_runs_and_first_route_wins(self):
		"""frappe hook convention: run all settlers, not only the first."""
		ref = SimpleNamespace(doctype="LMS Course Purchase", name="LMS-CP-0003")
		first = MagicMock(return_value="/lms/receipt")
		second = MagicMock(return_value=None)
		third = MagicMock(return_value="/lms/other")

		def fake_get_attr(path):
			return {"a": first, "b": second, "c": third}[path.rsplit(".", 1)[-1]]

		with (
			patch(f"{MODULE}.frappe.get_doc", return_value=ref),
			patch(
				f"{MODULE}.frappe.get_hooks",
				return_value={"LMS Course Purchase": ["fake_app.a", "fake_app.b", "fake_app.c"]},
			),
			patch(f"{MODULE}.frappe.get_attr", side_effect=fake_get_attr),
		):
			result = authorize_reference("LMS Course Purchase", "LMS-CP-0003", "Paid")

		first.assert_called_once_with(ref)
		second.assert_called_once_with(ref)
		third.assert_called_once_with(ref)
		self.assertEqual(result, "/lms/receipt")

	def test_unknown_reference_settles_to_none(self):
		ref = SimpleNamespace(doctype="Vanilla Doc", name="VD-0001")

		with (
			patch(f"{MODULE}.frappe.get_doc", return_value=ref),
			patch(f"{MODULE}.frappe.get_hooks", return_value={}),
		):
			self.assertIsNone(authorize_reference("Vanilla Doc", "VD-0001", "Paid"))

	def test_missing_pair_returns_none(self):
		self.assertIsNone(authorize_reference("", "", "Paid"))
