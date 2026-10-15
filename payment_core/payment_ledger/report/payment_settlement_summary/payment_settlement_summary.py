# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.query_builder import Criterion
from frappe.query_builder.functions import Count, Sum
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_rows(filters.from_date, filters.to_date)
	return columns, data


def get_columns():
	return [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 120},
		{"label": _("Captures"), "fieldname": "capture_count", "fieldtype": "Int", "width": 100},
		{"label": _("Captured Amount"), "fieldname": "captured", "fieldtype": "Currency", "width": 140},
		{"label": _("Refunds"), "fieldname": "refund_count", "fieldtype": "Int", "width": 100},
		{"label": _("Refunded Amount"), "fieldname": "refunded", "fieldtype": "Currency", "width": 140},
		{"label": _("Net Settled"), "fieldname": "net", "fieldtype": "Currency", "width": 140},
	]


def get_rows(from_date=None, to_date=None):
	Receipt = frappe.qb.DocType("Payment Receipt")  # per-site binding, not module-level
	conditions = [Receipt.docstatus == 1]
	if from_date:
		conditions.append(Receipt.posted_on >= f"{from_date} 00:00:00")
	if to_date:
		conditions.append(Receipt.posted_on <= f"{to_date} 23:59:59")

	query = (
		frappe.qb.from_(Receipt)
		.select(
			Receipt.posted_on.as_("posted"),
			Receipt.entry_type.as_("entry_type"),
			Sum(Receipt.amount).as_("total"),
			Count("*").as_("count"),
		)
		.where(Criterion.all(conditions))
		.groupby(Receipt.entry_type, Receipt.posted_on)
	)

	by_date = {}
	for row in query.run(as_dict=True):
		day = row.posted.date() if hasattr(row.posted, "date") else row.posted
		bucket = by_date.setdefault(
			day, {"captured": 0, "refunded": 0, "capture_count": 0, "refund_count": 0}
		)
		if row.entry_type == "Capture":
			bucket["captured"] += flt(row.total)
			bucket["capture_count"] += row.count
		else:
			bucket["refunded"] += flt(row.total)
			bucket["refund_count"] += row.count

	return [
		{
			"date": day,
			**bucket,
			"net": bucket["captured"] - bucket["refunded"],
		}
		for day, bucket in sorted(by_date.items())
	]
