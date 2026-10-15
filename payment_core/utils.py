# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Shared, gateway-agnostic helpers used across the payment gateway logic.

import time
from contextlib import contextmanager
from urllib.parse import urlencode

import frappe
from frappe import _
from frappe.model import default_fields
from frappe.query_builder.functions import Sum
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, flt, now_datetime, nowdate

from payment_core.payment_ledger.status_flow import (
	OPEN_TRANSACTION_STATUSES,
	PAYMENT_TRANSACTION_STATUSES,
	PaymentTransactionStatus,
)

# Gateway-side callers may still speak the legacy vocabulary; translate at
# the update boundary so every producer does not need migrating at once.
LEGACY_STATUS_MAP = {"Pending": "Initiated", "Authorized": "Initiated", "Completed": "Paid"}


def validate_integration_request(docname: str | None):
	if frappe.db.get_value("Integration Request", docname, "status") == "Cancelled":
		frappe.throw(_("Expired Token"))


def get_site_default_currency() -> str | None:
	"""The site's default currency when one is configured.

	ERPNext sites keep it in Global Defaults (an ERPNext doctype); plain
	Frappe sites carry the install-time currency in System Settings. Returns
	None when neither has one, letting the doctype default apply.
	"""
	if frappe.db.exists("DocType", "Global Defaults"):
		return frappe.db.get_single_value("Global Defaults", "default_currency")
	return frappe.db.get_single_value("System Settings", "currency")


def get_payment_gateway_controller(payment_gateway):
	"""Return payment gateway controller"""
	gateway = frappe.get_doc("Payment Gateway", payment_gateway)
	if gateway.gateway_controller is None:
		try:
			return frappe.get_doc(f"{payment_gateway} Settings")
		except Exception:
			frappe.throw(_("{0} Settings not found").format(payment_gateway))
	else:
		try:
			return frappe.get_doc(gateway.gateway_settings, gateway.gateway_controller)
		except Exception:
			frappe.throw(_("{0} Settings not found").format(payment_gateway))


@frappe.whitelist(allow_guest=True, xss_safe=True)  # nosemgrep: rules.security.guest-whitelisted-method
def get_checkout_url(**kwargs: str) -> dict | None:
	try:
		if kwargs.get("payment_gateway"):
			# Guest-reachable: only gateway labels with a registered Payment
			# Gateway row may resolve a settings doctype, never an arbitrary
			# caller-chosen DocType name.
			if not frappe.db.exists("Payment Gateway", {"gateway": kwargs.get("payment_gateway")}):
				raise ValueError("payment_gateway is not registered")
			doc = frappe.get_doc("{} Settings".format(kwargs.get("payment_gateway")))
			return doc.get_payment_url(**kwargs)
		else:
			raise ValueError("payment_gateway is required")
	except Exception:
		frappe.respond_as_web_page(
			_("Something went wrong"),
			_(
				"Looks like something is wrong with this site's payment gateway configuration. No payment has been made."
			),
			indicator_color="red",
			http_status_code=frappe.ValidationError.http_status_code,
		)


def create_payment_gateway(gateway, settings=None, controller=None):
	# NOTE: we don't translate Payment Gateway name because it is an internal doctype
	if not frappe.db.exists("Payment Gateway", gateway):
		payment_gateway = frappe.get_doc(
			{
				"doctype": "Payment Gateway",
				"gateway": gateway,
				"gateway_settings": settings,
				"gateway_controller": controller,
			}
		)
		payment_gateway.insert(ignore_permissions=True)


def get_customer_doctype():
	"""Customer DocType declared by a consuming app via the payment_customer_doctype hook.

	Used to type the transaction's Customer link so the desk can open the
	buyer's document directly. Returns None on sites without a declaring app.
	"""
	doctypes = frappe.get_hooks("payment_customer_doctype")
	return doctypes[0] if doctypes else None


# What payment_core needs to read from a payable reference document, and the
# built-in field-name candidates used when no Payment Field Mapping is set.
PAYMENT_REFERENCE_PURPOSES = (
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
)

REFERENCE_FIELD_DEFAULTS = {
	"amount": ("grand_total", "total", "amount", "net_total"),
	"currency": ("currency",),
	"payment_method": ("payment_method",),
	"customer_email": ("email", "customer_email"),
	"customer": (),
	"payer_name": ("customer_name",),
	"order_id": ("order_id", "po_number"),
	"due_date": ("due_date", "valid_till", "valid_until"),
	"payment_channel": ("payment_channel",),
	"phone_number": ("phone", "mobile_no", "phone_number"),
}

# Standard (non-DocField) reference fields usable as mapping targets, with
# the doctype their values link to.
STANDARD_FIELD_OPTIONS = {"owner": "User", "modified_by": "User"}


@frappe.whitelist()
def get_mappable_fields(doctype: str) -> list:
	"""Labels, fieldnames and fieldtypes that a Payment Field Mapping may target.

	Feeds the desk form's field pickers: every DocField (custom fields
	included, they are merged into meta) plus the standard fields that make
	sense as mapping targets. Requires read access to Payment Field Mapping.
	"""
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(_("DocType {0} does not exist").format(doctype))
	frappe.has_permission("Payment Field Mapping", "read", throw=True)
	# Same gate as the mapping builder: field labels/types are metadata, but
	# they still belong behind the target doctype's read permission.
	frappe.has_permission(doctype, "read", throw=True)

	fields = [
		{
			"fieldname": df.fieldname,
			"fieldtype": df.fieldtype,
			"label": _(df.label or frappe.unscrub(df.fieldname)),
		}
		for df in frappe.get_meta(doctype).fields
		if df.fieldtype
		not in ("Section Break", "Column Break", "HTML", "Button", "Tab Break", "Fold", "Heading")
	]
	fields.extend(
		{
			"fieldname": fieldname,
			"fieldtype": "Link",
			"label": _(frappe.unscrub(fieldname)),
		}
		for fieldname in STANDARD_FIELD_OPTIONS
	)
	fields.sort(key=lambda row: (row["label"].lower(), row["fieldname"]))
	return fields


MAPPING_FIELD_BY_PURPOSE = {
	"amount": "amount_field",
	"currency": "currency_field",
	"payment_method": "payment_method_field",
	"customer_email": "customer_email_field",
	"customer": "customer_field",
	"payer_name": "payer_name_field",
	"order_id": "order_id_field",
	"due_date": "due_date_field",
	"payment_channel": "payment_channel_field",
	"phone_number": "phone_number_field",
}


def get_reference_field_map(reference_doctype):
	"""Configured Payment Field Mapping row for a reference doctype, as purpose → fieldname."""
	if not frappe.db.table_exists("Payment Field Mapping"):
		return {}
	mapping_name = frappe.db.get_value(
		"Payment Field Mapping",
		{"reference_doctype": reference_doctype, "disabled": 0},
	)
	if not mapping_name:
		return {}
	rows = frappe.get_all(
		"Payment Field Mapping Item",
		filters={
			"parenttype": "Payment Field Mapping",
			"parent": mapping_name,
			"parentfield": "mapping",
		},
		fields=["purpose", "reference_field"],
	)
	return {row.purpose: row.reference_field for row in rows if row.purpose and row.reference_field}


def get_reference_field(reference_doctype, purpose):
	"""Resolve which reference field serves a purpose.

	A configured Payment Field Mapping wins; otherwise the built-in candidates
	apply. Returns None when the doctype has no usable field for the purpose.
	"""
	mapped = (get_reference_field_map(reference_doctype) or {}).get(purpose)
	meta = frappe.get_meta(reference_doctype)

	def has_field(fieldname):
		# default_fields (owner, modified_by, ...) are not DocFields but are
		# valid mapping targets.
		return meta.has_field(fieldname) or fieldname in default_fields

	if mapped and has_field(mapped):
		return mapped
	return next(
		(fieldname for fieldname in REFERENCE_FIELD_DEFAULTS.get(purpose, ()) if has_field(fieldname)),
		None,
	)


def map_reference_fields(reference_doctype, reference_docname):
	"""Read every resolvable payment field off a reference document.

	Returns {amount, currency, payment_method, customer_email, customer,
	payer_name}; unresolved purposes are None. Consuming apps can splat this
	into gateway ``get_payment_url`` kwargs and ``create_payment_transaction``.
	"""
	fieldnames = {}
	for purpose in PAYMENT_REFERENCE_PURPOSES:
		fieldname = get_reference_field(reference_doctype, purpose)
		if fieldname:
			# several purposes may resolve to the same field; keep all pairs
			fieldnames.setdefault(fieldname, []).append(purpose)
	values = frappe._dict({purpose: None for purpose in PAYMENT_REFERENCE_PURPOSES})
	if not fieldnames:
		return values
	row = frappe.db.get_value(reference_doctype, reference_docname, list(fieldnames), as_dict=True) or {}
	for fieldname, purposes in fieldnames.items():
		for purpose in purposes:
			values[purpose] = row.get(fieldname)
	return values


def auto_receipt_enabled() -> bool:
	"""Site-level default: write a Capture Payment Receipt when a payment completes.

	Read from Payment Core Settings; absent setting/table (pre-migrate, or a
	gateway-only site that never synced it) means off. An app that explicitly
	passes ``auto_receipt=True`` for its own flow gets receipts regardless.
	"""
	if not frappe.db.exists("DocType", "Payment Core Settings"):
		return False
	return bool(frappe.db.get_single_value("Payment Core Settings", "auto_create_receipt"))


def email_flow_enabled() -> bool:
	"""Site-level switch: email the buyer the payment link on submit.

	Mirrors ERPNext's Payment Request email behaviour for the shared ledger:
	on submit the buyer receives the checkout link with the reference
	document's print attached. Off (default) means the checkout link is used
	directly from the Payment Transaction.
	"""
	if not frappe.db.exists("DocType", "Payment Core Settings"):
		return False
	return bool(frappe.db.get_single_value("Payment Core Settings", "enable_email_flow"))


def send_payment_email(transaction_name: str, raise_on_failure: bool = False) -> str | None:
	"""Email the buyer the payment link with the reference document attached.

	Recipient is the transaction's ``customer_email`` (filled from the
	Payment Field Mapping at creation). The attachment follows ERPNext
	Payment Request: ``frappe.attach_print`` of the reference document, so
	PDF/HTML follows Print Settings and the reference's default print
	format. Attachment failures are logged and skipped - a dev bench
	without wkhtmltopdf access still gets the email with the link.
	Send failures are logged too (an unconfigured Email Account must not
	break the submit); the manual desk action passes
	``raise_on_failure`` so the user sees the cause.
	"""
	doc = frappe.get_cached_doc("Payment Transaction", transaction_name)
	if not (doc.customer_email and doc.checkout_url):
		return None

	subject = _("Payment Request for {0} {1}").format(doc.reference_doctype, doc.reference_docname)
	message = frappe.render_template(  # nosemgrep: rules.security.frappe-ssti
		"""
<p>{{ _("Hello") }} {{ payer_name }},</p>
<p>{{ _("A payment of") }} <b>{{ amount }}</b> {{ _("is due for") }} {{ reference_doctype }} {{ reference_docname }}.</p>
<p style="margin: 24px 0;">
	<a href="{{ checkout_url }}"
		style="background: #635bff; color: #fff; padding: 12px 28px; border-radius: 8px;
			text-decoration: none; font-weight: 600; display: inline-block;">
		{{ _("Pay Now") }}
	</a>
</p>
<p>{{ _("This link will open the secure checkout page.") }}</p>
""",
		{
			# Escaped on purpose: templates render without autoescape and
			# payer_name / reference values are client-suppliable.
			"payer_name": frappe.utils.escape_html(doc.payer_name or doc.customer_email),
			"amount": frappe.utils.fmt_money(doc.amount, currency=doc.currency),
			"reference_doctype": frappe.utils.escape_html(doc.reference_doctype),
			"reference_docname": frappe.utils.escape_html(doc.reference_docname),
			"checkout_url": doc.checkout_url,
		},
	)

	attachments = []
	try:
		attachments.append(
			frappe.attach_print(
				doc.reference_doctype,
				doc.reference_docname,
				file_name=doc.reference_docname,
			)
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Payment email print attachment failed")

	try:
		frappe.sendmail(
			recipients=doc.customer_email,
			subject=subject,
			message=message,
			attachments=attachments,
			# Queued, never inline: now=True makes frappe send inside this
			# request's after_commit, and an SMTP failure there raises past
			# this handler and 500s the buyer's checkout/submit.
			now=False,
		)
	except Exception:
		# The submit must never fail because email is unconfigured or the
		# SMTP send broke (ERPNext Payment Request defers to a background
		# job for the same reason). Log it; the manual button re-raises.
		frappe.log_error(frappe.get_traceback(), "Payment link email failed")
		if raise_on_failure:
			raise
	return doc.customer_email


@frappe.whitelist()
def resend_payment_email(name: str) -> str | None:
	"""Manually (re-)send the payment link email for a submitted transaction."""
	frappe.has_permission("Payment Transaction", "read", name, throw=True)
	if not email_flow_enabled():
		frappe.throw(_("Email flow is disabled in Payment Core Settings"))
	return send_payment_email(name, raise_on_failure=True)


def create_payment_transaction(
	reference_doctype,
	reference_docname,
	gateway,
	amount,
	currency=None,
	idempotency_key=None,
	customer_email=None,
	metadata=None,
	auto_receipt=False,
	payment_method=None,
	customer=None,
	provider_customer_id=None,
	payer_name=None,
	order_id=None,
	due_date=None,
	payment_channel=None,
	phone_number=None,
):
	"""Create or reuse a gateway-agnostic payment transaction.

	The transaction links a gateway attempt to any Frappe document. It has no
	ERPNext-specific fields, so an app can settle its own reference document in
	``on_payment_authorized``. Pass ``auto_receipt=True`` to also write the
	Capture Payment Receipt automatically once the transaction completes —
	for apps adopting the shared ledger. Apps keeping their own books leave it
	off so the same money is not counted twice.

	``payment_method``, ``customer_email`` and ``customer`` fall back to the
	reference document via its Payment Field Mapping (or the built-in field
	candidates); a mapped customer link field is used directly and its link
	options become the customer doctype, otherwise the buyer is looked up by
	email on the hook-declared customer doctype.
	"""
	if not reference_doctype or not reference_docname:
		frappe.throw(_("A payment reference is required."))
	if not gateway:
		frappe.throw(_("A payment gateway is required."))
	auto_receipt = bool(auto_receipt) or auto_receipt_enabled()
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Payment amount must be greater than zero."))

	if idempotency_key:
		existing = frappe.db.get_value(
			"Payment Transaction",
			{"idempotency_key": idempotency_key},
			["name", "reference_doctype", "reference_docname", "gateway"],
			as_dict=True,
		)
		if existing:
			if (existing.reference_doctype, existing.reference_docname, existing.gateway) != (
				reference_doctype,
				reference_docname,
				gateway,
			):
				frappe.throw(
					_("idempotency_key {0} is already used for another reference or gateway").format(
						idempotency_key
					)
				)
			return frappe.get_doc("Payment Transaction", existing.name)

	reference_context = map_reference_fields(reference_doctype, reference_docname)
	if payment_method is None:
		payment_method = reference_context.payment_method
	if customer_email is None:
		customer_email = reference_context.customer_email
	if payer_name is None:
		payer_name = reference_context.payer_name
	if order_id is None:
		order_id = reference_context.order_id
	if due_date is None:
		due_date = reference_context.due_date
	if payment_channel is None:
		payment_channel = reference_context.payment_channel
	if phone_number is None:
		phone_number = reference_context.phone_number

	customer_doctype = get_customer_doctype()
	customer_field = get_reference_field(reference_doctype, "customer")
	if customer is None and reference_context.customer:
		customer = reference_context.customer
		# A mapped link field types itself; no hook needed. Standard fields
		# (owner, modified_by) carry no meta, so their target is hardcoded.
		options = None
		if customer_field:
			field_meta = frappe.get_meta(reference_doctype).get_field(customer_field)
			options = getattr(field_meta, "options", None) or STANDARD_FIELD_OPTIONS.get(customer_field)
		if options:
			customer_doctype = options
	if customer is None and customer_doctype and customer_email:
		if frappe.get_meta(customer_doctype).has_field("email"):
			customer = frappe.db.get_value(customer_doctype, {"email": customer_email})

	transaction = frappe.get_doc(
		{
			"doctype": "Payment Transaction",
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
			"gateway": gateway,
			"amount": amount,
			"currency": currency or get_site_default_currency(),
			"idempotency_key": idempotency_key,
			"customer_email": customer_email,
			"customer_doctype": customer_doctype,
			"customer": customer,
			"payment_method": payment_method,
			"provider_customer_id": provider_customer_id,
			"payer_name": payer_name,
			"order_id": order_id,
			"valid_until": due_date,
			"payment_channel": payment_channel,
			"phone_number": phone_number,
			"outstanding_amount": amount,
			"initiated_by": frappe.session.user if frappe.session.user != "Guest" else None,
			"auto_receipt": 1 if auto_receipt else 0,
			"metadata": frappe.as_json(metadata or {}),
			"status": "Draft",
		}
	)
	return transaction.insert(ignore_permissions=True)


@frappe.whitelist()
def create_transaction_for_reference(
	reference_doctype: str,
	reference_docname: str,
	gateway: str,
	auto_receipt: bool = False,
) -> str:
	"""Create (or reuse) a mapped Payment Transaction for a reference document.

	Desk action behind the "Create Payment Transaction" button shown on mapped
	reference doctypes: reads the Payment Field Mapping, materializes the
	transaction, and returns its name. An open transaction for the same
	reference and gateway is reused instead of duplicating.
	"""
	frappe.has_permission("Payment Transaction", "create", throw=True)
	frappe.has_permission(reference_doctype, "read", throw=True)
	if not frappe.db.exists("Payment Field Mapping", {"reference_doctype": reference_doctype, "disabled": 0}):
		frappe.throw(_("No enabled Payment Field Mapping for {0}").format(frappe.bold(reference_doctype)))
	if not frappe.db.exists(reference_doctype, reference_docname):
		frappe.throw(_("{0} {1} does not exist").format(reference_doctype, frappe.bold(reference_docname)))

	gateway_row = frappe.db.get_value("Payment Gateway", gateway, ["gateway"], as_dict=True)
	if not gateway_row:
		frappe.throw(_("Payment Gateway {0} is not available").format(frappe.bold(gateway)))
	# gateway identity convention: "<label>:<Payment Gateway row name>" -- the
	# part after the first colon is how controllers resolve back to the row
	return ensure_reference_transaction(
		reference_doctype,
		reference_docname,
		f"{gateway_row.gateway}:{gateway}",
		auto_receipt=auto_receipt,
	)


def ensure_reference_transaction(reference_doctype, reference_docname, gateway_string, auto_receipt=False):
	"""Mapped Payment Transaction for a reference and gateway, reusing an open one.

	Checkout counterpart of the desk action: same mapping-driven creation, but
	without permission checks because the buyer's checkout runs as Guest
	(inserts use ignore_permissions, like the gateway-side ensure helpers).
	"""
	existing = frappe.db.get_value(
		"Payment Transaction",
		{
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
			"gateway": gateway_string,
			"status": ("in", ["Draft", "Requested", "Initiated"]),
		},
	)
	if existing:
		return existing

	context = map_reference_fields(reference_doctype, reference_docname)
	if context.amount is None:
		frappe.throw(
			_("No amount could be read from {0} {1}; map an amount field first").format(
				reference_doctype, frappe.bold(reference_docname)
			)
		)
	transaction = create_payment_transaction(
		reference_doctype=reference_doctype,
		reference_docname=reference_docname,
		gateway=gateway_string,
		amount=context.amount,
		currency=context.currency,
		payment_method=context.payment_method,
		customer_email=context.customer_email,
		customer=context.customer,
		payer_name=context.payer_name,
		order_id=context.order_id,
		due_date=context.due_date,
		payment_channel=context.payment_channel,
		phone_number=context.phone_number,
		auto_receipt=auto_receipt,
	)
	return transaction.name


def initiate_transaction(name):
	"""Submit a Draft transaction and return its gateway checkout URL.

	Programmatic counterpart of the desk user pressing Submit: ``on_submit``
	marks the transaction Requested and creates the payment URL (idempotent —
	a transaction that already carries a URL is not re-created). Elevated on
	purpose: the caller is the buyer's checkout session (usually Guest), the
	counterpart to guest-safe ``ensure_reference_transaction``.
	"""
	with elevated_user():
		doc = frappe.get_doc("Payment Transaction", name)
		if doc.docstatus == 0:
			doc.submit()
		url = doc.checkout_url or frappe.db.get_value("Payment Transaction", name, "checkout_url")
	return url


def update_payment_transaction(
	transaction_name,
	status=None,
	provider_transaction_id=None,
	checkout_url=None,
	error_message=None,
	paid_at=None,
	metadata=None,
	payment_method=None,
	provider_customer_id=None,
):
	"""Update a transaction idempotently after a provider response or webhook.

	Gateway-side callers may still use the legacy status vocabulary ("Pending",
	"Authorized", "Completed"); it is translated to the Payment Request-style
	states ("Initiated", "Paid") at this boundary. Reaching ``Paid`` drives the
	full settlement automatically: the auto-receipt is booked (exactly-once)
	and the reference document is authorized.
	"""
	if not transaction_name or not frappe.db.exists("Payment Transaction", transaction_name):
		return None
	status = LEGACY_STATUS_MAP.get(status, status)
	if status and status not in PAYMENT_TRANSACTION_STATUSES:
		frappe.throw(_("Invalid payment transaction status: {0}").format(status))
	values = {}
	if provider_transaction_id:
		values["provider_transaction_id"] = provider_transaction_id
	if provider_customer_id:
		values["provider_customer_id"] = provider_customer_id
	if checkout_url:
		values["checkout_url"] = checkout_url
	if error_message:
		values["error_message"] = error_message
	if payment_method:
		values["payment_method"] = payment_method
	if paid_at or status == PaymentTransactionStatus.PAID:
		values["paid_at"] = paid_at or now_datetime()
	if metadata is not None:
		# diagnostics accumulate over the transaction's life; merge, don't clobber
		existing = frappe.parse_json(
			frappe.db.get_value("Payment Transaction", transaction_name, "metadata") or "{}"
		)
		if not isinstance(existing, dict):
			existing = {}
		existing.update(metadata)
		values["metadata"] = frappe.as_json(existing)
	if values:
		frappe.db.set_value("Payment Transaction", transaction_name, values, update_modified=False)
	if status:
		# The forward-only guard lives in the status controller: a late,
		# out-of-order webhook must never regress a settled transaction
		# (Paid -> Initiated/Failed); such a status is ignored, not applied.
		PaymentTransactionStatus.apply(transaction_name, status)
	doc = frappe.get_cached_doc("Payment Transaction", transaction_name)
	if doc.docstatus == 0 and doc.status == PaymentTransactionStatus.PAID:
		# settlement reached a Draft (tests or legacy callers that never went
		# through submission): book it as the submitted voucher it now is
		doc.submit()
	if doc.status == PaymentTransactionStatus.PAID:
		# Every settlement path funnels through here (gateway finalize, webhook
		# backstop, desk action): book the auto-receipt exactly-once, then let
		# the receipt's submit sync + authorize the reference document.
		if doc.auto_receipt and not frappe.db.exists(
			"Payment Receipt",
			{"payment_transaction": transaction_name, "entry_type": "Capture", "docstatus": 1},
		):
			record_payment_receipt(
				transaction=transaction_name,
				amount=doc.amount,
				entry_type="Capture",
				method=doc.payment_method or "Online",
				provider_reference=doc.provider_transaction_id or "",
			)
		doc.reload()
		authorize_reference(doc.reference_doctype, doc.reference_docname, "Paid")
	return doc


def get_capture_balance(reference_doctype, reference_docname, exclude_name=None):
	"""Captured, refunded and net (captured - refunded) amounts for a reference.

	Computed from Payment Receipt rows, so it reflects money that actually
	moved, not transaction attempts.
	"""
	if not frappe.db.table_exists("Payment Receipt"):
		return {"captured": 0.0, "refunded": 0.0, "net": 0.0}
	filters = {
		"reference_doctype": reference_doctype,
		"reference_docname": reference_docname,
		"docstatus": 1,
	}
	if exclude_name:
		filters["name"] = ("!=", exclude_name)
	rows = frappe.get_all("Payment Receipt", filters=filters, fields=["entry_type", "amount"])
	captured = sum(flt(row.amount) for row in rows if row.entry_type == "Capture")
	refunded = sum(flt(row.amount) for row in rows if row.entry_type == "Refund")
	return {"captured": flt(captured), "refunded": flt(refunded), "net": flt(captured - refunded)}


def record_payment_receipt(
	transaction=None,
	reference_doctype=None,
	reference_docname=None,
	amount=None,
	entry_type="Capture",
	method="Online",
	gateway=None,
	currency=None,
	provider_reference="",
	remarks="",
):
	"""Write a Capture/Refund Payment Receipt against a reference document.

	Intended to be called from the reference's ``on_payment_authorized`` (and
	from refund flows). Idempotent for Capture: when ``transaction`` is given
	and already carries a Capture receipt, the existing receipt is returned so
	concurrent webhook + redirect settlement writes exactly one receipt.
	Reference fields and currency fall back to the transaction when omitted.
	"""
	if entry_type not in ("Capture", "Refund"):
		frappe.throw(_("Invalid receipt entry type: {0}").format(entry_type))

	if transaction and entry_type == "Capture":
		# Serialize concurrent settlement (webhook vs redirect vs desk): hold a
		# row lock on the transaction for the rest of this request so the
		# exists-check below cannot race a parallel insert. (MariaDB has no
		# partial unique indexes, and refunds legitimately repeat, so the lock
		# plus this in-lock re-check is the constraint.)
		Transaction = frappe.qb.DocType("Payment Transaction")
		frappe.qb.from_(Transaction).select(Transaction.name).where(
			Transaction.name == transaction
		).for_update().run()
		existing = frappe.db.get_value(
			"Payment Receipt",
			{"payment_transaction": transaction, "entry_type": "Capture", "docstatus": 1},
			"name",
		)
		if existing:
			return existing

	if transaction:
		stored = frappe.db.get_value(
			"Payment Transaction",
			transaction,
			["reference_doctype", "reference_docname", "currency", "gateway"],
			as_dict=True,
		)
		reference_doctype = reference_doctype or (stored and stored.reference_doctype)
		reference_docname = reference_docname or (stored and stored.reference_docname)
		currency = currency or (stored and stored.currency)
		gateway = gateway or (stored and stored.gateway)

	if not (reference_doctype and reference_docname):
		frappe.throw(_("A payment reference is required."))

	receipt = frappe.get_doc(
		{
			"doctype": "Payment Receipt",
			"payment_transaction": transaction,
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
			"entry_type": entry_type,
			"amount": flt(amount),
			"currency": currency or get_site_default_currency(),
			"method": method,
			"gateway": gateway,
			"provider_reference": provider_reference,
			"remarks": remarks,
		}
	)
	receipt.insert(ignore_permissions=True)
	receipt.submit()
	return receipt.name


def before_install():
	# Guard used during ERPNext CI patch tests (v10 restore path lacks Module Def.custom).
	if not frappe.get_meta("Module Def").has_field("custom"):
		return False


def is_v2_gateway(payment_gateway=None):
	"""Whether the gateway uses the V2 PaymentController contract.

	Gateways here implement the legacy V1 contract, so this is always False and
	ERPNext keeps its V1 flow. Exists so ERPNext can import it from payment_core.
	"""
	return False


@contextmanager
def optional_app_import_guard():
	"""No-op context manager for gateway apps guarding optional-app imports."""
	yield


# Compat alias: gateway apps import this name; to be dropped with their cleanup.
erpnext_app_import_guard = optional_app_import_guard


@contextmanager
def elevated_user(user: str = "Administrator"):
	"""Act as ``user`` for a scoped block without corrupting the live request.

	``frappe.set_user`` swaps the session identity (``session.sid`` and
	``session.data`` get overwritten; the after-response ``Session.update``
	then persists the broken record and the browser's next request resumes
	as "User None not found") AND clears request-scoped state — ``form_dict``,
	``cache``, ``role_permissions``, ``new_doc_templates``, ``user_perms``
	and the cached Jinja environments. Losing those mid-request blanks the
	payment-success page's template values after a same-request settlement
	and drops any form parameters the caller still needs. Snapshot
	everything ``set_user`` touches and restore it.
	"""
	local = frappe.local
	session = local.session
	cleared_keys = (
		"form_dict",
		"cache",
		"role_permissions",
		"new_doc_templates",
		"user_perms",
		"jenv_restricted",
		"jenv_unrestricted",
	)
	session_snapshot = {"user": session.get("user"), "sid": session.get("sid"), "data": session.get("data")}
	local_snapshot = {key: getattr(local, key, None) for key in cleared_keys}
	try:
		frappe.set_user(user)  # nosemgrep: rules.security.frappe-setuser
		yield
	finally:
		frappe.set_user(session_snapshot["user"] or "Guest")  # nosemgrep: rules.security.frappe-setuser
		session["sid"] = session_snapshot["sid"]
		session["data"] = session_snapshot["data"]
		for key, value in local_snapshot.items():
			if value is not None:
				setattr(local, key, value)


def guard_payment_reference(reference_doctype, reference_docname):
	"""Reject payment endpoints pointed at an arbitrary or non-existent reference.

	The reference must be a real document. Doctype read permission is
	deliberately NOT required: buyers of own-flow apps (e.g. LMS learners)
	access course content through the app's own UI, not desk doctype perms.
	Amount integrity is enforced separately — server-side from the reference
	when it exposes an amount field, else by the calling app's server code.
	"""
	if not (
		reference_doctype and reference_docname and frappe.db.exists(reference_doctype, reference_docname)
	):
		frappe.throw(_("Invalid payment reference."), frappe.PermissionError)


def get_reference_amount(reference_doctype, reference_docname):
	"""Authoritative payable amount + currency, read server-side from the reference.

	Never trust a client-supplied amount: without this an attacker can post any
	value (e.g. 0.01) and settle a full order for a token amount. Returns
	(None, None) when the reference exposes no amount field — own-flow apps
	(LMS-style) are then the amount authority themselves and must pass one.
	"""
	amount_field = get_reference_field(reference_doctype, "amount")
	currency_field = get_reference_field(reference_doctype, "currency")
	if not amount_field:
		return None, None
	fields = [amount_field] + ([currency_field] if currency_field else [])
	row = frappe.db.get_value(reference_doctype, reference_docname, fields, as_dict=True)
	if not row:
		frappe.throw(_("Payment reference {0} no longer exists.").format(reference_docname))
	return row.get(amount_field), row.get(currency_field)


def is_subscription_reference(data):
	"""Whether the payment reference is flagged as a subscription (is_a_subscription)."""
	dt, dn = data.get("reference_doctype"), data.get("reference_docname")
	if not dt or not dn or not frappe.db.exists(dt, dn):
		return False
	if not frappe.get_meta(dt).has_field("is_a_subscription"):
		return False
	return bool(frappe.db.get_value(dt, dn, "is_a_subscription"))


def success_redirect(metadata=None, reference_doctype=None, reference_docname=None):
	"""payment-success URL carrying the reference so the success page can load it."""
	metadata = metadata or {}
	dt = reference_doctype or metadata.get("reference_doctype")
	dn = reference_docname or metadata.get("reference_docname")
	if dt and dn:
		return f"payment-success?{urlencode({'doctype': dt, 'docname': dn})}"
	return "payment-success"


def settle_payment_request(pr, controller=None):
	"""Mark a submitted ERPNext Payment Request paid and create its Payment Entry.

	payment_core's built-in ERPNext integration: ``authorize_reference``
	dispatches here for the Payment Request doctype, which only exists when
	ERPNext is installed, so sites without ERPNext never reach this path. The
	amount actually charged is resolved through the gateway controller when it
	participates (``get_charged_amount``), else from the shared ledger's
	captured receipts, so a partial charge books a partial Payment Entry.
	"""
	if controller is None and getattr(pr, "payment_gateway", None):
		controller = get_payment_gateway_controller(pr.payment_gateway)

	if pr.docstatus != 1 or pr.status == "Paid":
		return
	if getattr(pr, "payment_channel", None) == "Phone":
		pr.db_set({"status": "Paid", "outstanding_amount": 0})
		return

	with erpnext_app_import_guard():
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
		from erpnext.accounts.doctype.payment_request.payment_request import (
			get_existing_payment_entry,
		)

	# Serialize webhook-vs-redirect settlement on the Payment Request row so
	# exactly one of them books the Payment Entry (the loser re-checks under
	# the lock and takes the second-PE branch or returns).
	if frappe.db.table_exists("Payment Request"):
		PaymentRequest = frappe.qb.DocType("Payment Request")
		frappe.qb.from_(PaymentRequest).select(PaymentRequest.name).where(
			PaymentRequest.name == pr.name
		).for_update().run()
		# Re-check from the DB under the lock: the in-memory pr can predate a
		# settlement that just completed in the racing request.
		if frappe.db.get_value("Payment Request", pr.name, "status") == "Paid":
			return

	# Allow a second PE when the reference document still has an outstanding balance.
	if pr.reference_name and get_existing_payment_entry(pr.reference_name):
		# Sales Orders don't have outstanding_amount — only block if the doctype has it and it's zero.
		if frappe.get_meta(pr.reference_doctype).has_field("outstanding_amount"):
			si_outstanding = flt(
				frappe.db.get_value(pr.reference_doctype, pr.reference_name, "outstanding_amount")
			)
			if si_outstanding <= 0:
				return

	charged_amount = _resolve_charged_amount(pr, controller)
	original_outstanding = flt(pr.outstanding_amount)
	if charged_amount and charged_amount < original_outstanding:
		pe_amount = charged_amount
	else:
		pe_amount = original_outstanding

	# For multi-currency, convert the charged amount to company currency using
	# the reference doc's exchange rate, because ERPNext's get_payment_entry
	# treats party_amount as the party-account currency (company currency for
	# most setups).
	company_currency = frappe.db.get_value("Company", pr.company, "default_currency")
	is_multi_currency = (pr.currency or "") != (company_currency or "")
	if is_multi_currency and charged_amount and charged_amount < original_outstanding:
		ref_conversion_rate = flt(
			frappe.db.get_value(pr.reference_doctype, pr.reference_name, "conversion_rate")
		)
		# Round to the company's currency precision so the PE amount matches what ERPNext books.
		currency_precision = (
			frappe.get_cached_value("System Settings", "System Settings", "currency_precision") or 2
		)
		pe_amount = flt(charged_amount * ref_conversion_rate, cint(currency_precision))
		# Cap to the actual outstanding so rounding never over-allocates.
		if frappe.get_meta(pr.reference_doctype).has_field("outstanding_amount"):
			ref_outstanding = flt(
				frappe.db.get_value(pr.reference_doctype, pr.reference_name, "outstanding_amount")
			)
			if ref_outstanding > 0:
				pe_amount = min(pe_amount, ref_outstanding)

	# Guest checkout cannot read/write Sales Invoice / PE; elevate for
	# settlement only (session-safe — see elevated_user).
	with elevated_user():
		payment_entry = get_payment_entry(
			pr.reference_doctype,
			pr.reference_name,
			party_amount=pe_amount,
			bank_account=pr.payment_account,
		)
		payment_entry.reference_no = pr.name
		payment_entry.reference_date = nowdate()
		payment_entry.insert(ignore_permissions=True)
		payment_entry.submit()

	# Close the Payment Request to match the money just booked (mirrors
	# ERPNext's set_as_paid). Without this the PR stays "Requested", the
	# idempotency guards above never engage, and a webhook + redirect +
	# retry race can book a second full Payment Entry.
	if pe_amount >= original_outstanding:
		pr.db_set({"status": "Paid", "outstanding_amount": 0})
	else:
		pr.db_set("outstanding_amount", flt(original_outstanding - pe_amount))

	# Gateway-specific stamps (provider ids on the PE) stay with the gateway.
	if controller is not None and hasattr(controller, "annotate_payment_entry"):
		controller.annotate_payment_entry(payment_entry, pr)
	return payment_entry


def _resolve_charged_amount(pr, controller=None):
	"""Amount the gateway actually charged for this Payment Request, if known.

	Gateway controllers report it through ``get_charged_amount``; without a
	participating controller the shared ledger's captured receipts for the
	reference are the truth. Zero means "unknown", settling the full
	outstanding instead.
	"""
	if controller is not None and hasattr(controller, "get_charged_amount"):
		return flt(controller.get_charged_amount(pr))
	balance = get_capture_balance("Payment Request", pr.name)
	return flt(balance.get("captured"))


def authorize_reference(reference_doctype, reference_docname, status_changed_to):
	"""Settle a reference document: duck-typed callback, then known doctypes, then settlers.

	Any app's payable doctype settles itself by defining
	``on_payment_authorized``. payment_core handles ERPNext's Payment Request
	natively (only present when ERPNext is installed); any other third-party
	doctype registers a settler via the ``payment_reference_settlers`` hook:
	``{"<DocType>": "path.to.callable"}`` receiving the reference document.
	"""
	if not (reference_doctype and reference_docname):
		return None
	ref = frappe.get_doc(reference_doctype, reference_docname)
	if hasattr(ref, "on_payment_authorized"):
		return ref.run_method("on_payment_authorized", status_changed_to)
	if ref.doctype == "Payment Request":
		# never return the Payment Entry document settle_payment_request
		# yields: callers treat this return as a redirect route, and a
		# document coerces into a bogus "Payment Entry (NAME)" URL. None lets
		# finalize_request land on its own payment-success URL.
		settle_payment_request(ref)
		return None
	settlers = frappe.get_hooks("payment_reference_settlers") or {}
	result = None
	for callable_path in settlers.get(reference_doctype, []):
		# frappe hook convention: run every registered settler, not only the
		# first; the first non-None result wins (callers treat it as a route).
		outcome = frappe.get_attr(callable_path)(ref)
		if outcome is not None and result is None:
			result = outcome
	return result


@frappe.whitelist()
def complete_payment_transaction(name: str, provider_reference: str = "") -> None:
	"""Desk action: confirm a gateway payment seen in the provider dashboard.

	Marks the transaction Paid; the settlement chain (auto-receipt booking and
	reference authorization) runs automatically inside the update.
	"""
	# manager-grade gate: Payment User deliberately lacks cancel, so
	# settlement/cancel/refund stay Payment Manager (or System Manager) actions
	frappe.has_permission("Payment Transaction", "cancel", name, throw=True)
	transaction = frappe.db.get_value(
		"Payment Transaction", name, ["status", "reference_doctype", "reference_docname"], as_dict=True
	)
	if not transaction:
		frappe.throw(_("Payment Transaction {0} does not exist").format(name))
	if transaction.status not in OPEN_TRANSACTION_STATUSES:
		frappe.throw(_("Only open transactions can be completed"))

	update_payment_transaction(
		name,
		status="Paid",
		provider_transaction_id=provider_reference or None,
		metadata={"desk_confirmed_by": frappe.session.user},
	)


@frappe.whitelist()
def cancel_payment_transaction(name: str) -> None:
	"""Desk action: abandon an open transaction."""
	# manager-grade gate: Payment User deliberately lacks cancel, so
	# settlement/cancel/refund stay Payment Manager (or System Manager) actions
	frappe.has_permission("Payment Transaction", "cancel", name, throw=True)
	status = frappe.db.get_value("Payment Transaction", name, "status")
	if not status:
		frappe.throw(_("Payment Transaction {0} does not exist").format(name))
	doc = frappe.get_doc("Payment Transaction", name)
	if doc.status not in (*OPEN_TRANSACTION_STATUSES, "Partially Paid", "Failed"):
		frappe.throw(_("Only open transactions can be cancelled"))
	if doc.docstatus == 0:
		doc.db_set("status", "Cancelled")
	else:
		doc.cancel()


def reconcile_reference_payments(reference_doctype, reference_docname, retries=2, delay=2):
	"""Re-confirm open gateway payments for a reference (webhook backstop).

	Providers can still report a session as processing when the buyer is
	redirected back, so the shared payment-success page asks the gateway
	controller to re-confirm. Provider apps implement ``reconcile_transaction``
	on their gateway settings controller; settlement itself is idempotent, so
	this is safe for webhook + redirect + page render arriving together.
	"""
	if not frappe.db.table_exists("Payment Transaction"):
		# gateway-only site: settlement is the app's own flow's business
		return []
	transactions = frappe.get_all(
		"Payment Transaction",
		filters={
			"reference_doctype": reference_doctype,
			"reference_docname": reference_docname,
			"status": ("in", OPEN_TRANSACTION_STATUSES),
		},
		pluck="name",
	)
	for name in transactions:
		controller = _get_gateway_controller_for_transaction(name)
		if not controller or not hasattr(controller, "reconcile_transaction"):
			continue
		for _attempt in range(retries + 1):
			# savepoint per row: a failing reconcile must not roll back the
			# transactions already settled in this same request
			frappe.db.savepoint("reference_reconcile")
			try:
				controller.reconcile_transaction(name)
			except Exception:
				frappe.db.rollback(save_point="reference_reconcile")
				frappe.log_error(frappe.get_traceback(), "Payment reconcile failed")
				# one failing reference must not starve the rest of the loop
				continue
			if frappe.db.get_value("Payment Transaction", name, "status") not in OPEN_TRANSACTION_STATUSES:
				break
			time.sleep(delay)


def resolve_gateway_controller(gateway_string):
	"""Resolve the settings controller behind a ``<label>:<Payment Gateway row>`` string."""
	gateway_string = gateway_string or ""
	# rsplit: the Payment Gateway row name is the LAST colon-separated token,
	# so labels that themselves contain a colon survive
	settings_name = gateway_string.rsplit(":", 1)[1] if ":" in gateway_string else gateway_string
	if not settings_name or not frappe.db.exists("Payment Gateway", settings_name):
		return None
	try:
		return get_payment_gateway_controller(settings_name)
	except Exception:
		return None


def _get_gateway_controller_for_transaction(transaction_name):
	"""Resolve a transaction's gateway settings controller, if it can be found."""
	gateway = frappe.db.get_value("Payment Transaction", transaction_name, "gateway") or ""
	return resolve_gateway_controller(gateway)


@frappe.whitelist()
def refund_payment_transaction(name: str, amount: float, reason: str = "") -> str:
	"""Execute a provider refund for a transaction and record the Refund receipt.

	Delegates to the gateway controller's ``refund_transaction`` (the provider
	moves the money) and writes the ledger entry with the provider's refund id,
	idempotent per that id. Requires write permission on Payment Transaction.
	"""
	# manager-grade gate: Payment User deliberately lacks cancel, so
	# settlement/cancel/refund stay Payment Manager (or System Manager) actions
	frappe.has_permission("Payment Transaction", "cancel", name, throw=True)
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Refund amount must be greater than zero"))
	transaction = frappe.db.get_value(
		"Payment Transaction", name, ["status", "provider_transaction_id"], as_dict=True
	)
	if not transaction:
		frappe.throw(_("Payment Transaction {0} does not exist").format(name))
	if transaction.status not in ("Paid", "Partially Paid"):
		frappe.throw(_("Only paid transactions can be refunded"))

	controller = _get_gateway_controller_for_transaction(name)
	if not controller or not hasattr(controller, "refund_transaction"):
		frappe.throw(_("The gateway for this transaction does not support refunds"))

	# Serialize concurrent refunds: hold the transaction row lock through the
	# balance check and the receipt write, so two refunds cannot both pass on
	# the same balance (the receipt-side check stays as the submit backstop).
	PaymentTransaction = frappe.qb.DocType("Payment Transaction")
	frappe.qb.from_(PaymentTransaction).select(PaymentTransaction.name).where(
		PaymentTransaction.name == name
	).for_update().run()

	# Validate the ledger balance BEFORE the provider moves money: a post-hoc
	# receipt validation error could not un-refund at the provider, leaving
	# ledger and provider out of sync.
	Receipt = frappe.qb.DocType("Payment Receipt")
	captured, refunded = (
		frappe.qb.from_(Receipt)
		.select(
			Sum(frappe.qb.terms.Case().when(Receipt.entry_type == "Capture", Receipt.amount).else_(0)),
			Sum(frappe.qb.terms.Case().when(Receipt.entry_type == "Refund", Receipt.amount).else_(0)),
		)
		.where((Receipt.payment_transaction == name) & (Receipt.docstatus == 1))
		.run()[0]
	)
	available = flt(captured) - flt(refunded)
	if flt(amount) > available:
		frappe.throw(
			_("Refund of {0} exceeds the refundable balance {1} for {2}").format(
				frappe.utils.fmt_money(amount), frappe.utils.fmt_money(available), frappe.bold(name)
			)
		)

	provider_refund_id = controller.refund_transaction(name, amount, reason)
	if not provider_refund_id:
		frappe.throw(_("The gateway did not return a refund reference"))
	if frappe.db.exists("Payment Receipt", {"provider_reference": provider_refund_id}):
		return frappe.db.get_value("Payment Receipt", {"provider_reference": provider_refund_id}, "name")
	return record_payment_receipt(
		transaction=name,
		amount=amount,
		entry_type="Refund",
		method=frappe.db.get_value("Payment Transaction", name, "payment_method"),
		provider_reference=provider_refund_id,
		remarks=reason,
	)


@frappe.whitelist(allow_guest=True, xss_safe=True)  # nosemgrep: rules.security.guest-whitelisted-method
@rate_limit(limit=20, seconds=60)
def reconcile_payment_status(doctype: str, docname: str) -> str:
	"""Re-check a reference's open payments once; return the latest status.

	Called by the shared success page's poller while the provider session
	still reads as processing. Safe for guests: settlement only happens when
	the provider confirms the payment, and it is idempotent. Rate-limited so
	anonymous callers cannot hammer the provider API. The Payment Transaction
	lookup comes first so unknown doctype/name pairs are indistinguishable
	from never-paid ones - no document-existence oracle for guests.
	"""
	if not frappe.db.table_exists("Payment Transaction"):
		# gateway-only site: the app's own flow owns the status
		return ""
	latest = frappe.db.get_value(
		"Payment Transaction",
		{"reference_doctype": doctype, "reference_docname": docname},
		"status",
		# creation, not modified: status writes deliberately keep modified
		# untouched (update_modified=False), so it cannot order attempts
		order_by="creation desc",
	)
	if not latest:
		# no transaction ever targeted this reference; do not reveal whether
		# the doctype or the document itself exists
		return ""
	reconcile_reference_payments(doctype, docname, retries=0, delay=0)
	return (
		frappe.db.get_value(
			"Payment Transaction",
			{"reference_doctype": doctype, "reference_docname": docname},
			"status",
			order_by="creation desc",
		)
		or ""
	)
