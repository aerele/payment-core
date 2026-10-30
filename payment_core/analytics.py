# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Payment analytics data for the Payment Analytics Desk page.

The whitelisted ``get_analytics`` endpoint is the single source for the
Frappe Chart dashboard and its filters, cards, and payment lists.
"""

import datetime

import frappe
from frappe import _
from frappe.query_builder.functions import Coalesce, Count, Date, Max, Sum
from frappe.utils import add_days, flt, nowdate, pretty_date

from payment_core.analytics_adapters import adapted_payload
from payment_core.analytics_display import (
	RANGE_LABELS,
	STATUS_COLORS,
	build_area_chart,
	build_donut,
	get_gateways,
	get_health_warnings,
	load_gateway_controllers,
	resolve_since,
)

OPEN_STATUSES = ("Draft", "Requested", "Initiated")


def enforce_access():
	"""Gate the dashboard on payment roles.

	These roles are *by design* granted global payment visibility: managers
	must see every customer, amount and failure across the site, including
	records they could not read individually. That intent is documented here
	and in the README; do not add per-record filtering without revisiting it.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please log in to view payment analytics."), frappe.PermissionError)
	roles = frappe.get_roles()
	if not {"Payment Manager", "Payment User", "System Manager"} & set(roles):
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def valid_day_window(value):
	"""Normalize a per-card day window ("today"/"7"/.../"all") or None."""
	if value in RANGE_LABELS:
		return value
	return None


@frappe.whitelist()
def get_analytics(
	range_key: str = "30",
	reference_doctype: str | None = None,
	recent_days: str | None = None,
	open_days: str | None = None,
	currency: str | None = None,
) -> dict:
	"""Display-ready analytics for the Payment Analytics Desk page.

	``reference_doctype`` scopes every widget to one payable doctype — on an
	ERPNext site that is typically Payment Request; custom apps see their own
	doctypes (Part Order, Part Invoice, ...). Unset means all doctypes.
	``recent_days`` / ``open_days`` override the recent-payments and
	open-payments lists with their own day windows, independent of the
	global ``range``. ``currency`` scopes every money figure; unset picks the
	highest-volume currency of the range (``currencies`` lists them all).
	"""
	enforce_access()
	if range_key not in RANGE_LABELS:
		range_key = "30"
	reference_doctype = reference_doctype or None
	recent_days = valid_day_window(recent_days)
	open_days = valid_day_window(open_days)
	since = resolve_since(range_key)
	if not frappe.db.table_exists("Payment Transaction") or not frappe.db.table_exists("Payment Receipt"):
		# gateway-only site: report on the site's own payment flow instead —
		# ERPNext's Payment Request / Payment Entry by default, or a custom
		# app's doctypes via the payment_analytics_adapter hook.
		return adapted_payload(since, range_key, reference_doctype, recent_days, open_days, currency)
	currencies = get_range_currencies(since)
	currency = currency if currency in currencies else (currencies[0] if currencies else None)
	controllers = load_gateway_controllers()
	recent = get_recent_transactions(reference_doctype, recent_days)
	for row in recent:
		row["when_display"] = pretty_date(row.get("paid_at") or row["creation"])
	return {
		"range": range_key,
		"reference_doctype": reference_doctype,
		"recent_days": recent_days,
		"open_days": open_days,
		"currency": currency,
		"currencies": currencies,
		"health_warnings": get_health_warnings(controllers),
		"gateways": get_gateways(controllers),
		"ranges": {key: _(label) for key, label in RANGE_LABELS.items()},
		"day_windows": {key: _(label) for key, label in RANGE_LABELS.items()},
		"doctype_breakdown": get_reference_doctype_breakdown(since, currency),
		"kpis": get_kpis(since, reference_doctype, currency),
		"chart": build_area_chart(get_daily_series(since, range_key, reference_doctype, currency)),
		"donut": build_donut(get_method_breakdown(since, reference_doctype, currency)),
		"top_customers": get_top_customers(since, reference_doctype, currency),
		"recent": recent,
		"open_payments": get_open_payments(reference_doctype, open_days),
		"failed_payments": get_failed_payments(reference_doctype),
	}


def get_range_currencies(since):
	"""Currencies with money in the range, highest volume first.

	Includes currencies from paid Payment Transactions that have no capture
	receipt (apps keeping their own books, e.g. ERPNext) - a receiptless-only
	range still discovers its currencies. Receipt-backed payments count only
	once: a submitted capture already makes its transaction Paid, so the
	paid-transaction query explicitly EXCLUDES receipt-backed rows.
	"""
	receipt = frappe.qb.DocType("Payment Receipt")
	transaction = frappe.qb.DocType("Payment Transaction")

	receipt_query = (
		frappe.qb.from_(receipt)
		.select(receipt.currency, Sum(receipt.amount).as_("total"))
		.where((receipt.entry_type == "Capture") & (receipt.docstatus == 1))
		.groupby(receipt.currency)
	)
	if since:
		receipt_query = receipt_query.where(receipt.posted_on >= f"{since} 00:00:00")
	volumes = {row.currency: flt(row.total) for row in receipt_query.run(as_dict=True) if row.currency}

	# receiptless paid transactions only: LEFT JOIN matches only submitted
	# Capture receipts (mirroring the companion query) - anything the receipt
	# side counted excludes the transaction here, so no double-count
	receiptless_query = (
		frappe.qb.from_(transaction)
		.left_join(receipt)
		.on(
			(receipt.payment_transaction == transaction.name)
			& (receipt.docstatus == 1)
			& (receipt.entry_type == "Capture")
		)
		.select(transaction.currency, Sum(transaction.amount).as_("total"))
		.where(transaction.status == "Paid")
		.where(receipt.name.isnull())
		.groupby(transaction.currency)
	)
	if since:
		receiptless_query = receiptless_query.where(transaction.paid_at >= f"{since} 00:00:00")
	for row in receiptless_query.run(as_dict=True):
		if row.currency:
			volumes[row.currency] = volumes.get(row.currency, 0) + flt(row.total)

	return sorted(volumes, key=volumes.get, reverse=True)


def _capture_query(since, reference_doctype=None, currency=None):
	"""Aggregation-ready query over submitted capture receipts, currency-scoped.

	docstatus == 1 is mandatory: cancelled captures (docstatus 2) and drafts
	must never contribute to any analytics total.
	"""
	receipt = frappe.qb.DocType("Payment Receipt")
	query = frappe.qb.from_(receipt).where((receipt.entry_type == "Capture") & (receipt.docstatus == 1))
	if since:
		query = query.where(receipt.posted_on >= f"{since} 00:00:00")
	if reference_doctype:
		query = query.where(receipt.reference_doctype == reference_doctype)
	if currency:
		query = query.where(receipt.currency == currency)
	return query, receipt


def get_kpis(since, reference_doctype=None, currency=None):
	"""Gross volume, successful payments, distinct buyers, average value.

	Aggregated in SQL - "All time" must not load whole tables into request
	memory. Buyers stay a distinct-row read (their identity spans three
	fallback columns), bounded by the number of distinct buyers.
	"""
	if not frappe.db.table_exists("Payment Receipt"):
		return {"gross": 0, "successful": 0, "customers": 0, "average": 0, "currency": None}
	query, receipt = _capture_query(since, reference_doctype, currency)
	gross, capture_count = (
		query.select(Sum(receipt.amount).as_("gross"), Count(receipt.name).as_("payments"))
		.run(as_list=True)
		.pop(0)
	)
	gross = flt(gross)
	capture_count = flt(capture_count)

	transaction = frappe.qb.DocType("Payment Transaction")
	count_query = frappe.qb.from_(transaction).select(Count(transaction.name))
	count_query = count_query.where(transaction.status == "Paid")
	# buyer identity matches top-customers exactly: typed (customer_doctype,
	# customer) for linked buyers, ("email", ...) / ("payer", ...) for
	# fallbacks - so both widgets agree on who is one customer
	buyer_query = (
		frappe.qb.from_(transaction)
		.select(
			transaction.customer,
			transaction.customer_doctype,
			transaction.customer_email,
			transaction.payer_name,
		)
		.where(transaction.status == "Paid")
	)
	if since:
		cutoff = f"{since} 00:00:00"
		count_query = count_query.where(transaction.paid_at >= cutoff)
		buyer_query = buyer_query.where(transaction.paid_at >= cutoff)
	if reference_doctype:
		count_query = count_query.where(transaction.reference_doctype == reference_doctype)
		buyer_query = buyer_query.where(transaction.reference_doctype == reference_doctype)
	if currency:
		count_query = count_query.where(transaction.currency == currency)
		buyer_query = buyer_query.where(transaction.currency == currency)
	successful_count = int(flt(count_query.run(as_list=True)[0][0]))
	# buyers stay a distinct-row read (identity spans three fallback columns),
	# bounded by the number of distinct buyers rather than table size
	buyers = {
		(row.customer_doctype, row.customer)
		if row.customer
		else ("email", row.customer_email)
		if row.customer_email
		else ("payer", row.payer_name)
		for row in buyer_query.distinct().run(as_dict=True)
	}

	# single-source counts: receipts back gross/average (the money that
	# actually moved), transactions back the successful count and buyers -
	# never mix the two sources in one ratio
	return {
		"gross": gross,
		"successful": successful_count,
		"customers": len(buyers),
		"average": (gross / capture_count) if capture_count else 0,
		"currency": currency,
	}


def get_daily_series(since, range_key, reference_doctype=None, currency=None):
	"""[{date, total}] captured amounts per day, gaps filled with zero."""
	if not frappe.db.table_exists("Payment Receipt"):
		return []
	query, receipt = _capture_query(since, reference_doctype, currency)
	rows = (
		query.select(Date(receipt.posted_on).as_("day"), Sum(receipt.amount).as_("total"))
		.groupby(Date(receipt.posted_on))
		.orderby(Date(receipt.posted_on))
		.run(as_dict=True)
	)
	daily = {row.day: flt(row.total) for row in rows}

	if range_key == "all":
		days = sorted(daily)
	else:
		start = datetime.date.fromisoformat(since)
		count = 1 if range_key == "today" else int(range_key)
		days = [start + datetime.timedelta(days=offset) for offset in range(count)]
	return [{"date": day.strftime("%d %b"), "total": round(flt(daily.get(day, 0)), 2)} for day in days]


def get_method_breakdown(since, reference_doctype=None, currency=None):
	"""Capture totals by payment method, largest first."""
	query, receipt = _capture_query(since, reference_doctype, currency)
	rows = (
		query.select(receipt.method, Sum(receipt.amount).as_("total"))
		.groupby(receipt.method)
		.orderby(Sum(receipt.amount), order=frappe.qb.desc)
		.run(as_dict=True)
	)
	ordered = [(row.method or _("Unknown"), flt(row.total)) for row in rows]
	total = sum(value for _key, value in ordered)
	return [
		{"method": key, "total": round(value, 2), "percent": (value / total * 100) if total else 0}
		for key, value in ordered
	]


def get_recent_transactions(reference_doctype=None, recent_days=None):
	if not frappe.db.table_exists("Payment Transaction"):
		return []
	filters = {}
	if reference_doctype:
		filters["reference_doctype"] = reference_doctype
	if recent_days and recent_days != "all":
		window = resolve_since(recent_days)
		filters["modified"] = (">=", f"{window} 00:00:00")
	rows = frappe.get_all(
		"Payment Transaction",
		filters=filters,
		fields=[
			"name",
			"reference_doctype",
			"reference_docname",
			"amount",
			"currency",
			"status",
			"customer",
			"customer_email",
			"paid_at",
			"creation",
		],
		order_by="modified desc",
		limit=8,
	)
	for row in rows:
		row["buyer"] = row.customer or row.customer_email or "—"
		row["badge"] = STATUS_COLORS.get(row.status, "grey")
	return rows


def get_open_payments(reference_doctype=None, open_days=None):
	if not frappe.db.table_exists("Payment Transaction"):
		return []
	filters = {"status": ("in", OPEN_STATUSES)}
	if reference_doctype:
		filters["reference_doctype"] = reference_doctype
	if open_days and open_days != "all":
		window = resolve_since(open_days)
		filters["creation"] = (">=", f"{window} 00:00:00")
	return frappe.get_all(
		"Payment Transaction",
		filters=filters,
		fields=["name", "reference_docname", "amount", "currency", "status", "creation"],
		order_by="creation desc",
		limit=5,
	)


def get_failed_payments(reference_doctype=None):
	if not frappe.db.table_exists("Payment Transaction"):
		return []
	filters = {"status": "Failed"}
	if reference_doctype:
		filters["reference_doctype"] = reference_doctype
	return frappe.get_all(
		"Payment Transaction",
		filters=filters,
		fields=["name", "reference_docname", "amount", "currency", "error_message", "creation"],
		order_by="creation desc",
		limit=5,
	)


def get_reference_doctype_breakdown(since, currency=None):
	"""Captured volume per payable doctype over the range — the scope pills.

	Always computed across all doctypes so the pills stay stable while one
	of them is selected. Receipts-only, consistent with every other
	receipt-backed widget (gross, series, methods, top customers). Gateway-
	only/ERPNext sites get their own breakdown from the adapter.
	"""
	if not frappe.db.table_exists("Payment Receipt"):
		return []
	query, receipt = _capture_query(since, None, currency)
	rows = (
		query.select(
			receipt.reference_doctype,
			Sum(receipt.amount).as_("captured"),
			Count(receipt.name).as_("payments"),
		)
		.groupby(receipt.reference_doctype)
		.run(as_dict=True)
	)
	totals = {
		(row.reference_doctype or _("Unknown")): {
			"captured": flt(row.captured),
			"count": flt(row.payments),
		}
		for row in rows
	}

	ordered = sorted(totals.items(), key=lambda item: item[1]["captured"], reverse=True)
	return [
		{
			"doctype": doctype,
			"captured": round(values["captured"], 2),
			"count": values["count"],
		}
		for doctype, values in ordered
	]


def get_top_customers(since, reference_doctype=None, currency=None, limit=5):
	"""Top buyers by captured money, honoring each site's customer doctype.

	Payment Receipt carries no customer fields, so receipts join their
	Payment Transaction; buyers without a customer link fall back to the
	email/payer name recorded on the transaction. Canonical identity is
	COALESCE(customer, customer_email, payer_name) computed in SQL, grouped
	there, and limited there - no unbounded variant read at request time.
	customer_doctype only surfaces when the identity IS a linked customer
	(not an email/payer fallback), so the UI never renders a dead link.
	"""
	if not frappe.db.table_exists("Payment Receipt"):
		return []
	receipt = frappe.qb.DocType("Payment Receipt")
	transaction = frappe.qb.DocType("Payment Transaction")
	identity = Coalesce(transaction.customer, transaction.customer_email, transaction.payer_name)
	# identity type keeps unrelated identities apart: a linked customer named
	# "john@acme.com" is NOT the email-fallback buyer "john@acme.com"
	identity_type = (
		frappe.qb.terms.Case()
		.when(transaction.customer.notnull(), "customer")
		.when(transaction.customer_email.notnull(), "email")
		.else_("payer")
	)
	# linked customers with the same name but different doctypes are different
	# buyers; fallbacks (email/payer) group under a neutral empty string
	identity_doctype = Coalesce(transaction.customer_doctype, "")
	query = (
		frappe.qb.from_(receipt)
		.join(transaction)
		.on(receipt.payment_transaction == transaction.name)
		.select(
			identity.as_("label"),
			identity_type.as_("identity_type"),
			Max(transaction.customer_doctype).as_("customer_doctype"),
			Max(transaction.customer).as_("customer"),
			Sum(receipt.amount).as_("captured"),
			Count(receipt.name).as_("payments"),
		)
		.where((receipt.entry_type == "Capture") & (receipt.docstatus == 1))
		.groupby(identity, identity_type, identity_doctype)
		.orderby(Sum(receipt.amount), order=frappe.qb.desc)
		.limit(limit)
	)
	if since:
		query = query.where(receipt.posted_on >= f"{since} 00:00:00")
	if reference_doctype:
		query = query.where(receipt.reference_doctype == reference_doctype)
	if currency:
		query = query.where(receipt.currency == currency)

	return [
		{
			"label": row.label or "—",
			# only surface the doctype when the buyer IS a linked customer;
			# an email/payer identity has no customer form to link to
			"customer_doctype": row.customer_doctype if row.customer else None,
			"captured": round(flt(row.captured), 2),
			"count": int(flt(row.payments)),
		}
		for row in query.run(as_dict=True)
	]
