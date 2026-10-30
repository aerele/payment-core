# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Analytics adapters for gateway-only sites.

Where an app owns its payment flow, the shared ledger does not exist and the
analytics report on the flow's own doctypes instead: ERPNext's Payment
Request / Payment Entry out of the box, and any custom app through the
``payment_analytics_adapter`` hook. Adapters return the same display payload
the ledger analytics produce, so the dashboard and page render unchanged.
"""

import datetime

import frappe
from frappe import _
from frappe.query_builder.functions import Count, Sum
from frappe.utils import flt

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
from payment_core.mode import gateway_only_reason


def get_adapter():
	"""The analytics adapter for a gateway-only site, if any.

	ERPNext is built in; custom apps register
	``payment_analytics_adapter = "app.module.build_analytics"`` returning the
	same payload shape (see ``adapted_payload`` for the contract).
	"""
	if "erpnext" in frappe.get_installed_apps():
		return erpnext_adapter
	hooks = frappe.get_hooks("payment_analytics_adapter") or []
	if hooks:
		return frappe.get_attr(hooks[0])
	return None


def _call_adapter(adapter, since, range_key, reference_doctype, recent_days, open_days=None, currency=None):
	"""Invoke a ``payment_analytics_adapter`` hook callable.

	Contract: ``adapter(since, range_key, reference_doctype, *, recent_days,
	open_days, currency)``. All keyword arguments have defaults, so a
	minimal adapter accepting only the first three works unchanged.
	"""
	return adapter(
		since,
		range_key,
		reference_doctype,
		recent_days=recent_days,
		open_days=open_days,
		currency=currency,
	)


def adapted_payload(
	since, range_key, reference_doctype=None, recent_days=None, open_days=None, currency=None
):
	"""Compose the display payload from the site's own payment flow."""
	adapter = get_adapter()
	if adapter:
		return _call_adapter(adapter, since, range_key, reference_doctype, recent_days, open_days, currency)
	controllers = load_gateway_controllers()
	return {
		"range": range_key,
		"reference_doctype": None,
		"recent_days": recent_days,
		"open_days": open_days,
		"currency": currency,
		"currencies": [],
		"day_windows": {key: _(label) for key, label in RANGE_LABELS.items()},
		"ledger_installed": False,
		"data_source": None,
		"mode_note": gateway_only_reason() or "Shared ledger not installed on this site",
		"health_warnings": get_health_warnings(controllers),
		"gateways": get_gateways(controllers),
		"ranges": {key: _(label) for key, label in RANGE_LABELS.items()},
		"doctype_breakdown": [],
		"kpis": {"gross": 0, "successful": 0, "customers": 0, "average": 0},
		"chart": build_area_chart([]),
		"donut": build_donut([]),
		"top_customers": [],
		"recent": [],
		"open_payments": [],
		"failed_payments": [],
	}


def erpnext_adapter(
	since, range_key, reference_doctype=None, recent_days=None, open_days=None, currency=None
):
	"""Analytics from ERPNext's own flow: Payment Request + Payment Entry.

	``recent_days`` / ``open_days`` narrow the recent and open lists to a
	tighter day window than the chart's ``range_key`` period.
	"""

	# flow money: Payment Entries booked against Payment Requests, joined and
	# aggregated in SQL (the old version loaded every entry of the range into
	# request memory). Currency is scoped on the Payment Request - Payment
	# Entry has no plain currency column.
	payment_entry = frappe.qb.DocType("Payment Entry")
	payment_entry_reference = frappe.qb.DocType("Payment Entry Reference")
	payment_request = frappe.qb.DocType("Payment Request")
	base = (
		frappe.qb.from_(payment_entry)
		.join(payment_entry_reference)
		.on(payment_entry_reference.parent == payment_entry.name)
		.join(payment_request)
		.on(payment_entry_reference.payment_request == payment_request.name)
		.where(payment_entry.docstatus == 1)
		.where(payment_entry.payment_type == "Receive")
	)
	if since:
		base = base.where(payment_entry.posting_date >= since)
	if reference_doctype and reference_doctype != "Payment Request":
		base = base.where(payment_request.reference_doctype == reference_doctype)

	currency_rows = (
		base.select(
			payment_request.currency,
			Sum(payment_entry_reference.allocated_amount).as_("total"),
		)
		.groupby(payment_request.currency)
		.orderby(Sum(payment_entry_reference.allocated_amount), order=frappe.qb.desc)
		.run(as_dict=True)
	)
	currencies = [row.currency for row in currency_rows if row.currency]
	currency = currency if currency in currencies else (currencies[0] if currencies else None)
	if currency:
		base = base.where(payment_request.currency == currency)

	gross, successful = (
		base.select(
			Sum(payment_entry_reference.allocated_amount).as_("gross"),
			Count(payment_entry.name).distinct().as_("payments"),
		)
		.run(as_list=True)
		.pop(0)
	)
	gross = flt(gross)
	successful = int(flt(successful))

	daily = {}
	for row in (
		base.select(payment_entry.posting_date, Sum(payment_entry_reference.allocated_amount).as_("total"))
		.groupby(payment_entry.posting_date)
		.run(as_dict=True)
	):
		daily[row.posting_date] = flt(row.total)

	if range_key == "all":
		days = sorted(daily)
	else:
		start_date = datetime.date.fromisoformat(since)
		count = 1 if range_key == "today" else int(range_key)
		days = [start_date + datetime.timedelta(days=offset) for offset in range(count)]
	series = [{"date": day.strftime("%d %b"), "total": round(flt(daily.get(day, 0)), 2)} for day in days]

	methods = {}
	for row in (
		base.select(payment_entry.mode_of_payment, Sum(payment_entry_reference.allocated_amount).as_("total"))
		.groupby(payment_entry.mode_of_payment)
		.orderby(Sum(payment_entry_reference.allocated_amount), order=frappe.qb.desc)
		.run(as_dict=True)
	):
		methods[row.mode_of_payment or _("Gateway")] = flt(row.total)
	ordered = sorted(methods.items(), key=lambda item: item[1], reverse=True)
	total = sum(value for _key, value in ordered)
	donut_input = [
		{"method": key, "total": round(value, 2), "percent": (value / total * 100) if total else 0}
		for key, value in ordered
	]

	customer_totals = {}
	for row in (
		base.select(
			payment_entry.party,
			payment_entry.party_type,
			Sum(payment_entry_reference.allocated_amount).as_("captured"),
			Count(payment_entry.name).distinct().as_("payments"),
		)
		.groupby(payment_entry.party, payment_entry.party_type)
		.orderby(Sum(payment_entry_reference.allocated_amount), order=frappe.qb.desc)
		.limit(10)
		.run(as_dict=True)
	):
		if not row.party:
			continue
		customer_totals[row.party] = {
			"label": row.party,
			"customer_doctype": row.party_type,
			"captured": round(flt(row.captured), 2),
			"count": int(flt(row.payments)),
		}
	top_customers = sorted(customer_totals.values(), key=lambda item: item["captured"], reverse=True)[:5]
	# distinct count is NOT capped by the top-customer limit
	parties = int(flt(base.select(Count(payment_entry.party).distinct()).run(as_list=True)[0][0]))

	request_filters = {}
	if recent_days and recent_days != "all":
		window = resolve_since(recent_days)
		request_filters["modified"] = (">=", f"{window} 00:00:00")
	reference_scope = reference_doctype or "Payment Request"
	if reference_scope != "Payment Request":
		# narrow to PRs raised against that reference document type
		request_filters["reference_doctype"] = reference_scope
	if currency:
		request_filters["currency"] = currency
	recent = []
	if reference_scope == "Payment Request" or reference_doctype:
		rows = frappe.get_all(
			"Payment Request",
			filters=request_filters,
			fields=[
				"name",
				"status",
				"grand_total",
				"currency",
				"party",
				"party_name",
				"email_to",
				"transaction_date",
				"failed_reason",
			],
			order_by="modified desc",
			limit=8,
		)
		for row in rows:
			recent.append(
				{
					"name": row.name,
					"reference_doctype": "Payment Request",
					"reference_docname": row.name,
					"route": f"/app/payment-request/{row.name}",
					"buyer": row.party_name or row.party or row.email_to or "—",
					"amount": row.grand_total,
					"currency": row.currency,
					"status": row.status,
					"badge": STATUS_COLORS.get(row.status, "grey"),
					"when": row.transaction_date,
					"when_display": frappe.utils.pretty_date(frappe.utils.get_datetime(row.transaction_date))
					if row.transaction_date
					else "—",
				}
			)

	open_filters = {"status": ("in", ("Draft", "Requested", "Initiated", "Partially Paid"))}
	if open_days and open_days != "all":
		open_window = resolve_since(open_days)
		open_filters["creation"] = (">=", f"{open_window} 00:00:00")
	if reference_doctype and reference_doctype != "Payment Request":
		open_filters["reference_doctype"] = reference_doctype
	if currency:
		open_filters["currency"] = currency
	open_payments = [
		{
			"name": row.name,
			"reference_doctype": "Payment Request",
			"reference_docname": row.name,
			"route": f"/app/payment-request/{row.name}",
			"amount": row.grand_total,
			"currency": row.currency,
			"status": row.status,
			"creation": row.creation,
		}
		for row in frappe.get_all(
			"Payment Request",
			filters=open_filters,
			fields=["name", "grand_total", "currency", "status", "creation"],
			order_by="creation desc",
			limit=5,
		)
	]
	failed_filters = {"status": "Failed"}
	if reference_doctype and reference_doctype != "Payment Request":
		failed_filters["reference_doctype"] = reference_doctype
	if currency:
		failed_filters["currency"] = currency
	failed_payments = [
		{
			"name": row.name,
			"reference_doctype": "Payment Request",
			"reference_docname": row.name,
			"route": f"/app/payment-request/{row.name}",
			"amount": row.grand_total,
			"currency": row.currency,
			"error_message": row.failed_reason or "",
		}
		for row in frappe.get_all(
			"Payment Request",
			filters=failed_filters,
			fields=["name", "grand_total", "currency", "failed_reason"],
			order_by="creation desc",
			limit=5,
		)
	]

	controllers = load_gateway_controllers()
	return {
		"range": range_key,
		"reference_doctype": reference_doctype,
		"recent_days": recent_days,
		"open_days": open_days,
		"currency": currency,
		"currencies": currencies,
		"day_windows": {key: _(label) for key, label in RANGE_LABELS.items()},
		"ledger_installed": False,
		"data_source": _("Payment Request / Payment Entry (ERPNext)"),
		"mode_note": None,
		"health_warnings": get_health_warnings(controllers),
		"gateways": get_gateways(controllers),
		"ranges": {key: _(label) for key, label in RANGE_LABELS.items()},
		"doctype_breakdown": [
			{"doctype": "Payment Request", "captured": round(gross, 2), "count": successful}
		]
		if successful
		else [],
		"kpis": {
			"gross": round(gross, 2),
			"successful": successful,
			"customers": parties,
			"average": round(gross / successful, 2) if successful else 0,
		},
		"chart": build_area_chart(series),
		"donut": build_donut(donut_input),
		"top_customers": top_customers,
		"recent": recent,
		"open_payments": open_payments,
		"failed_payments": failed_payments,
	}
