# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Payment Field Mapping + reference-field resolution coverage. A fresh Note is
# the reference doctype so tests stay inside payment_core. Mappings are
# one-per-doctype, so each test cleans up after itself (tests in a class share
# one transaction in FrappeTestCase).

from unittest import skipUnless

import frappe
from frappe.tests.utils import FrappeTestCase

from payment_core.field_mapping import get_mapping_builder_data, save_mapping_builder_data
from payment_core.mode import ledger_installed
from payment_core.utils import (
	create_payment_transaction,
	create_transaction_for_reference,
	get_mappable_fields,
	get_reference_amount,
	get_reference_field,
	get_reference_field_map,
	map_reference_fields,
)


def _make_note(title=None):
	return (
		frappe.get_doc({"doctype": "Note", "title": title or frappe.generate_hash(length=8), "public": 1})
		.insert(ignore_permissions=True)
		.name
	)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class MappingTestCase(FrappeTestCase):
	def make_mapping(self, reference_doctype="Note", **purposes):
		"""Create a mapping; the amount purpose is always mapped (to ``title``)."""
		rows = [{"purpose": "amount", "reference_field": "title"}]
		rows.extend(
			{"purpose": purpose, "reference_field": fieldname} for purpose, fieldname in purposes.items()
		)
		doc = frappe.get_doc(
			{"doctype": "Payment Field Mapping", "reference_doctype": reference_doctype, "mapping": rows}
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.db.delete,
			"Payment Field Mapping Item",
			{"parenttype": "Payment Field Mapping", "parent": doc.name},
		)
		self.addCleanup(frappe.db.delete, "Payment Field Mapping", {"reference_doctype": reference_doctype})
		return doc.name


class TestFieldMappingDoctype(MappingTestCase):
	def test_rejects_unknown_mapped_field(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_mapping(payer_name="not_a_note_field")

	def test_rejects_second_enabled_mapping_for_same_doctype(self):
		self.make_mapping()
		with self.assertRaises(frappe.ValidationError):
			self.make_mapping()

	def test_disabled_mapping_may_coexist(self):
		first = self.make_mapping()
		frappe.db.set_value("Payment Field Mapping", first, "disabled", 1)
		self.make_mapping()

	def test_rejects_duplicate_purpose(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Payment Field Mapping",
					"reference_doctype": "Note",
					"mapping": [
						{"purpose": "amount", "reference_field": "title"},
						{"purpose": "amount", "reference_field": "public"},
					],
				}
			).insert(ignore_permissions=True)

	def test_rejects_unknown_purpose(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Payment Field Mapping",
					"reference_doctype": "Note",
					"mapping": [
						{"purpose": "amount", "reference_field": "title"},
						{"purpose": "happiness", "reference_field": "title"},
					],
				}
			).insert(ignore_permissions=True)

	def test_requires_an_amount_purpose(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Payment Field Mapping",
					"reference_doctype": "Note",
					"mapping": [{"purpose": "payer_name", "reference_field": "title"}],
				}
			).insert(ignore_permissions=True)


class TestReferenceFieldResolution(MappingTestCase):
	def test_mapping_overrides_defaults(self):
		self.make_mapping()
		self.assertEqual(get_reference_field("Note", "amount"), "title")

	def test_unmapped_purpose_falls_back_to_defaults(self):
		self.assertEqual(get_reference_field_map("Note"), {})
		self.assertIsNone(get_reference_field("Note", "amount"))

	def test_removed_mapped_field_falls_back(self):
		# a mapping naming a field that was later removed from the doctype
		# must not break resolution (db.set_value bypasses validate here)
		name = self.make_mapping(payer_name="title")
		amount_row = frappe.db.get_value(
			"Payment Field Mapping Item", {"parent": name, "purpose": "amount"}, "name"
		)
		frappe.db.set_value("Payment Field Mapping Item", amount_row, "reference_field", "not_a_field")
		self.assertIsNone(get_reference_field("Note", "amount"))
		self.assertEqual(get_reference_field("Note", "payer_name"), "title")

	def test_disabled_mapping_is_ignored(self):
		name = self.make_mapping(payer_name="title")
		frappe.db.set_value("Payment Field Mapping", name, "disabled", 1)
		self.assertEqual(get_reference_field_map("Note"), {})

	def test_map_reference_fields_returns_context(self):
		note = _make_note()
		self.make_mapping(customer="owner", payer_name="title")

		context = map_reference_fields("Note", note)

		self.assertEqual(context.customer, "Administrator")
		self.assertEqual(context.payer_name, frappe.db.get_value("Note", note, "title"))
		self.assertEqual(context.amount, frappe.db.get_value("Note", note, "title"))


class TestMapperIntegration(MappingTestCase):
	def test_get_reference_amount_uses_mapped_field(self):
		note = _make_note("4242")
		self.make_mapping()

		amount, _currency = get_reference_amount("Note", note)
		self.assertEqual(amount, "4242")

	def test_transaction_uses_mapped_customer_link_and_infers_doctype(self):
		note = _make_note()
		self.make_mapping(customer="owner", payer_name="title")

		transaction = create_payment_transaction(
			reference_doctype="Note",
			reference_docname=note,
			gateway="Stripe:Test",
			amount=100,
		)

		row = frappe.db.get_value(
			"Payment Transaction", transaction.name, ["customer", "customer_doctype"], as_dict=True
		)
		self.assertEqual(row.customer, "Administrator")
		self.assertEqual(row.customer_doctype, "User")


class TestMappableFieldsEndpoint(MappingTestCase):
	def test_lists_doctype_fields_and_standard_fields(self):
		fields = {row["fieldname"]: row for row in get_mappable_fields("Note")}
		self.assertEqual(fields["title"]["fieldtype"], "Data")
		self.assertEqual(fields["title"]["label"], "Title")
		self.assertEqual(fields["public"]["fieldtype"], "Check")
		self.assertEqual(fields["owner"]["fieldtype"], "Link")  # standard field included
		self.assertEqual(fields["owner"]["label"], "Owner")
		self.assertEqual(fields["modified_by"]["label"], "Modified By")

	def test_layout_fields_are_excluded(self):
		fields = [row["fieldname"] for row in get_mappable_fields("Note")]
		self.assertNotIn("sections", fields)

	def test_rejects_unknown_doctype(self):
		with self.assertRaises(frappe.ValidationError):
			get_mappable_fields(doctype="Not A Doctype")


class TestMappingBuilderEndpoints(MappingTestCase):
	def test_builder_returns_static_purposes_and_stored_rows(self):
		name = self.make_mapping(payer_name="title")

		data = get_mapping_builder_data("Note")

		self.assertEqual(data["mapping_name"], name)
		self.assertEqual(
			[purpose["purpose"] for purpose in data["purposes"]],
			[
				"amount",
				"currency",
				"payment_method",
				"customer_email",
				"customer",
				"payer_name",
				"order_id",
				"due_date",
				"payment_channel",
				"phone_number",
			],
		)
		self.assertEqual(
			{row["purpose"]: row["reference_field"] for row in data["mapping"]}["payer_name"],
			"title",
		)

	def test_builder_save_updates_existing_mapping(self):
		name = self.make_mapping()

		result = save_mapping_builder_data(
			"Note",
			[
				{"purpose": "amount", "reference_field": "title"},
				{"purpose": "payer_name", "reference_field": "title"},
			],
		)

		self.assertEqual(result["name"], name)
		self.assertEqual(
			frappe.db.get_value(
				"Payment Field Mapping Item",
				{"parent": name, "purpose": "payer_name"},
				"reference_field",
			),
			"title",
		)

	def test_builder_save_requires_amount(self):
		with self.assertRaises(frappe.ValidationError):
			save_mapping_builder_data("Note", [{"purpose": "payer_name", "reference_field": "title"}])


class TestNewPurposes(MappingTestCase):
	def test_context_carries_new_purposes(self):
		note = _make_note()
		self.make_mapping(order_id="title", payer_name="title")

		context = map_reference_fields("Note", note)

		self.assertEqual(context.order_id, frappe.db.get_value("Note", note, "title"))
		self.assertEqual(context.payer_name, frappe.db.get_value("Note", note, "title"))
		self.assertIsNone(context.due_date)

	def test_transaction_stores_resolved_context(self):
		note = _make_note()
		self.make_mapping(payer_name="title", order_id="title")

		transaction = create_payment_transaction(
			reference_doctype="Note",
			reference_docname=note,
			gateway="Stripe:Test",
			amount=100,
		)

		row = frappe.db.get_value(
			"Payment Transaction",
			transaction.name,
			["payer_name", "order_id", "outstanding_amount"],
			as_dict=True,
		)
		title = frappe.db.get_value("Note", note, "title")
		self.assertEqual(row.payer_name, title)
		self.assertEqual(row.order_id, title)
		self.assertEqual(row.outstanding_amount, 100)


class TestCreateTransactionForReference(MappingTestCase):
	def _make_gateway(self):
		suffix = frappe.generate_hash(length=6).title()
		gateway = frappe.get_doc(
			{
				"doctype": "Payment Gateway",
				"gateway": f"Note GW {suffix}",
				"gateway_settings": "Note",
				"gateway_controller": _make_note(),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Payment Gateway", gateway.name, force=True)
		return gateway.name

	def test_creates_mapped_transaction_and_reuses_open_one(self):
		note = _make_note("150")
		self.make_mapping(payer_name="title")
		gateway = self._make_gateway()

		first = create_transaction_for_reference("Note", note, gateway)
		row = frappe.db.get_value(
			"Payment Transaction",
			first,
			["amount", "payer_name", "gateway", "status"],
			as_dict=True,
		)
		self.assertEqual(row.amount, 150)
		self.assertEqual(row.payer_name, "150")
		self.assertTrue(row.gateway.startswith("Note GW"))
		self.assertEqual(row.status, "Draft")

		# an open transaction for the same reference and gateway is reused
		self.assertEqual(create_transaction_for_reference("Note", note, gateway), first)

	def test_requires_a_mapping(self):
		note = _make_note("150")
		gateway = self._make_gateway()
		with self.assertRaises(frappe.ValidationError):
			create_transaction_for_reference("Note", note, gateway)


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestPartialPayments(FrappeTestCase):
	def test_partial_capture_marks_partially_paid_with_outstanding(self):
		from payment_core.utils import record_payment_receipt

		reference = _make_note()
		transaction = create_payment_transaction(
			reference_doctype="Note", reference_docname=reference, gateway="Stripe:Test", amount=100
		)

		record_payment_receipt(transaction=transaction.name, amount=40)

		row = frappe.db.get_value(
			"Payment Transaction", transaction.name, ["status", "outstanding_amount"], as_dict=True
		)
		self.assertEqual(row.status, "Partially Paid")
		self.assertEqual(row.outstanding_amount, 60)

	def test_full_capture_does_not_touch_status(self):
		from payment_core.utils import record_payment_receipt

		reference = _make_note()
		transaction = create_payment_transaction(
			reference_doctype="Note", reference_docname=reference, gateway="Stripe:Test", amount=100
		)

		record_payment_receipt(transaction=transaction.name, amount=100)

		# Payment Entry parity: booking the full capture marks the transaction Paid
		status = frappe.db.get_value("Payment Transaction", transaction.name, "status")
		self.assertEqual(status, "Paid")


@skipUnless(ledger_installed(), "shared ledger not installed (gateway-only site)")
class TestCustomFieldGuard(FrappeTestCase):
	def _make_custom_field(self):
		# NOTE: cleanup is mandatory — each insert ALTERs a column onto frappe's
		# core Note table, and leftovers accumulate across runs until MariaDB's
		# 65535-byte row limit breaks every later ALTER ("Row size too large").
		custom_field = frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": "Note",
				"fieldname": "custom_mapped_phone_" + frappe.generate_hash(length=4).lower(),
				"label": "Mapped Phone",
				"fieldtype": "Data",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: (
				frappe.delete_doc("Custom Field", custom_field.name, ignore_permissions=True)
				if frappe.db.exists("Custom Field", custom_field.name)
				else None
			)
		)
		return custom_field

	def test_trash_blocked_while_mapped(self):
		custom_field = self._make_custom_field()
		frappe.get_doc(
			{
				"doctype": "Payment Field Mapping",
				"reference_doctype": "Note",
				"mapping": [
					{"purpose": "amount", "reference_field": "title"},
					{"purpose": "phone_number", "reference_field": custom_field.fieldname},
				],
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.db.delete, "Payment Field Mapping", {"reference_doctype": "Note"})
		self.addCleanup(frappe.db.delete, "Custom Field", custom_field.name)

		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Custom Field", custom_field.name)

	def test_trash_allowed_after_mapping_removed(self):
		custom_field = self._make_custom_field()
		self.addCleanup(frappe.db.delete, "Custom Field", {"name": ("like", custom_field.fieldname + "%")})

		frappe.delete_doc("Custom Field", custom_field.name)
		self.assertFalse(frappe.db.exists("Custom Field", custom_field.name))
