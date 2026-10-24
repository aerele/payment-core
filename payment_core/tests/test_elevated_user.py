# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Regression tests for the session-safe user elevation used by settlement
# paths (guest checkout settlement, Stripe webhook dispatch). Plain
# frappe.set_user wipes session.data and overwrites session.sid; the
# after-response Session.update write-back persists that broken record and
# the browser's next request resumes with session.user = None ("User None
# not found" on the page it lands on).

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.utils import elevated_user


class TestElevatedUser(FrappeTestCase):
	def setUp(self):
		# restore the real session afterwards: the fake one must not leak
		self._real_session = frappe.local.session
		self.addCleanup(self._restore_session)

	def _restore_session(self):
		frappe.local.session = self._real_session
		frappe.set_user("Administrator")

	def _fake_session(self):
		inner = frappe._dict({"user": "buyer@example.com", "session_expiry": "06:00:00"})
		frappe.local.session = frappe._dict({"user": "buyer@example.com", "sid": "abc123", "data": inner})
		return inner

	def test_elevation_restores_session_keys(self):
		inner = self._fake_session()

		with elevated_user("Administrator"):
			self.assertEqual(frappe.session.user, "Administrator")

		self.assertEqual(frappe.session.user, "buyer@example.com")
		self.assertEqual(frappe.local.session["sid"], "abc123")
		self.assertIs(frappe.local.session["data"], inner)

	def test_elevation_restores_on_error(self):
		inner = self._fake_session()

		with self.assertRaises(ValueError):
			with elevated_user("Administrator"):
				raise ValueError("boom")

		self.assertEqual(frappe.session.user, "buyer@example.com")
		self.assertIs(frappe.local.session["data"], inner)

	def test_none_user_snapshot_defaults_to_guest(self):
		frappe.local.session = frappe._dict({"user": None, "sid": None, "data": frappe._dict()})

		with elevated_user("Administrator"):
			self.assertEqual(frappe.session.user, "Administrator")

		self.assertEqual(frappe.session.user, "Guest")

	def test_elevation_preserves_request_state(self):
		"""set_user also clears form_dict/cache/role_permissions mid-request.

		A settlement running inside the payment-success page render used to
		blank the page's own query parameters (doctype/docname/redirect_to),
		killing the status poller and the buyer's redirect.
		"""
		self._fake_session()
		originals = {
			key: getattr(frappe.local, key, None) for key in ("form_dict", "cache", "role_permissions")
		}
		frappe.local.form_dict = frappe._dict({"doctype": "Part Order", "docname": "SPO-1"})
		frappe.local.cache = {"payment": "state"}
		frappe.local.role_permissions = {"Payment Transaction": {"read": 1}}
		form_dict = frappe.local.form_dict

		def _restore():
			for key, value in originals.items():
				if value is not None:
					setattr(frappe.local, key, value)

		self.addCleanup(_restore)

		with elevated_user("Administrator"):
			self.assertEqual(frappe.local.form_dict.get("doctype"), None)
			self.assertEqual(frappe.local.role_permissions, {})

		self.assertIs(frappe.local.form_dict, form_dict)
		self.assertEqual(frappe.local.form_dict.get("docname"), "SPO-1")
		self.assertEqual(frappe.local.cache, {"payment": "state"})
		self.assertEqual(frappe.local.role_permissions, {"Payment Transaction": {"read": 1}})
