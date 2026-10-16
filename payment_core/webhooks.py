# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Provider-neutral webhook intake for gateway apps (Payment Webhook Log).

Gateways verify signatures themselves, then record every delivery here and
process it inside their own savepoint, marking the log row at the end. The
unique ``event_id`` is the dedupe guard; a prior *Failed* row is reused so
providers can retry transient failures.
"""

import frappe
from frappe import _

from payment_core.utils import get_payment_gateway_controller, resolve_gateway_controller

DUPLICATE = {"status": "duplicate"}


def get_or_create_log(
	source,
	event_id,
	event_type,
	payload=None,
	provider_reference=None,
	signature_valid=True,
):
	"""Return (log_doc, None) for a fresh delivery, or (None, DUPLICATE)."""
	prior = frappe.db.get_value(
		"Payment Webhook Log", {"event_id": event_id}, ["name", "status"], as_dict=True
	)
	if prior and prior.status != "Failed":
		return None, DUPLICATE
	if prior:
		return frappe.get_doc("Payment Webhook Log", prior.name), None

	log = frappe.get_doc(
		{
			"doctype": "Payment Webhook Log",
			"source": source,
			"event_id": event_id,
			"event_type": event_type,
			"provider_reference": provider_reference,
			"signature_valid": 1 if signature_valid else 0,
			"status": "Received",
			"payload": frappe.as_json(payload) if payload is not None else None,
		}
	)
	try:
		log.insert()
	except (frappe.exceptions.UniqueValidationError, frappe.exceptions.DuplicateEntryError):
		# Concurrent delivery already inserted it; the unique event_id index
		# is the guard and raises UniqueValidationError (base_document),
		# DuplicateEntryError covers a name collision the same way
		return None, DUPLICATE
	return log, None


def mark_processed(name, status="Processed", reference_doctype=None, reference_docname=None):
	values = {"status": status}
	if reference_doctype:
		values["reference_doctype"] = reference_doctype
	if reference_docname:
		values["reference_docname"] = reference_docname
	frappe.db.set_value("Payment Webhook Log", name, values, update_modified=False)


def mark_failed(name, error):
	frappe.db.set_value(
		"Payment Webhook Log",
		name,
		{"status": "Failed", "error": str(error or "")[:1000]},
		update_modified=False,
	)


@frappe.whitelist()
def retry_failed(name: str) -> None:
	"""Desk action: re-run a gateway's processor for a Failed webhook."""
	frappe.has_permission("Payment Webhook Log", "write", throw=True)
	if frappe.db.get_value("Payment Webhook Log", name, "status") != "Failed":
		frappe.throw(_("Only Failed webhook logs can be retried"))
	controller = _resolve_source_controller(frappe.db.get_value("Payment Webhook Log", name, "source"))
	if not controller or not hasattr(controller, "process_webhook_log"):
		frappe.throw(_("The source gateway does not support webhook retries"))
	controller.process_webhook_log(name)


def _resolve_source_controller(source):
	# Same resolution rules as the rest of payment_core (rsplit on the last
	# colon) so gateway labels that themselves contain a colon survive.
	return resolve_gateway_controller(str(source or ""))
