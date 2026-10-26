# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Shared display constants and chart builders for payment analytics.

Imported by both ``analytics`` (ledger sites) and ``analytics_adapters``
(gateway-only sites), so neither imports the other.
"""

import frappe
from frappe import _
from frappe.utils import add_days, nowdate

from payment_core.utils import get_payment_gateway_controller

RANGE_LABELS = {
	"today": "Today",
	"7": "Last 7 days",
	"30": "Last 30 days",
	"90": "Last 90 days",
	"all": "All time",
}
STATUS_COLORS = {
	"Paid": "green",
	"Completed": "green",
	"Initiated": "grey",
	"Requested": "orange",
	"Draft": "grey",
	"Pending": "orange",
	"Failed": "red",
	"Cancelled": "grey",
	"Refunded": "purple",
}


def resolve_since(range_key):
	if range_key == "all":
		return None
	if range_key == "today":
		return nowdate()
	return add_days(nowdate(), -int(range_key) + 1)


def build_area_chart(series):
	"""Return the data shape consumed by ``frappe.Chart``."""
	return {
		"data": {
			"labels": [point["date"] for point in series],
			"datasets": [{"name": _("Captured"), "values": [point["total"] for point in series]}],
		}
	}


def build_donut(methods):
	"""Return the data shape consumed by a Frappe donut chart."""
	return {
		"data": {
			"labels": [item["method"] for item in methods],
			"datasets": [{"values": [item["total"] for item in methods]}],
		},
		"total": sum(item["total"] for item in methods),
	}


def load_gateway_controllers():
	"""Resolve every gateway's settings controller exactly once per request.

	Returns [(gateway_row, controller_or_None)]: callers derive health
	warnings and the dashboard card list from the same resolution pass
	instead of loading settings twice.
	"""
	results = []
	for row in frappe.get_all("Payment Gateway", fields=["name", "gateway_settings", "gateway_controller"]):
		try:
			controller = get_payment_gateway_controller(row.name)
		except Exception:
			# a broken settings doc is itself a health problem - surface it,
			# never swallow it silently on the health dashboard
			frappe.log_error(
				title=f"Gateway health check failed for {row.name}",
				message=frappe.get_traceback(),
			)
			results.append((row, None))
			continue
		results.append((row, controller))
	return results


def get_health_warnings(controllers=None):
	"""Gateway setup gaps reported by controllers that implement the check."""
	warnings = []
	seen = set()
	if controllers is None:
		controllers = load_gateway_controllers()
	for row, controller in controllers:
		if controller is None:
			warnings.append(_("Gateway {0} could not be checked").format(frappe.bold(row.name)))
			continue
		if getattr(controller, "name", None) in seen:
			continue  # several gateways may share one settings doc
		seen.add(getattr(controller, "name", None))
		if hasattr(controller, "get_health_warnings"):
			warnings.extend(controller.get_health_warnings() or [])
	return warnings


def get_gateways(controllers=None):
	"""Installed gateways with health, for the dashboard card."""
	gateways = []
	seen = set()
	if controllers is None:
		controllers = load_gateway_controllers()
	for row, controller in controllers:
		if row.gateway_controller in seen:
			continue
		seen.add(row.gateway_controller)
		warnings = []
		if controller is None:
			warnings = [_("Settings could not be loaded")]
		elif hasattr(controller, "get_health_warnings"):
			warnings = controller.get_health_warnings() or []
		# the desk router slug: frappe.desk.utils.slug, not frappe.scrub
		# (scrub's underscores resolve as a Page route and 404)
		settings_slug = frappe.desk.utils.slug(row.gateway_settings) if row.gateway_settings else None
		route = (
			f"/app/{settings_slug}/{row.gateway_controller}"
			if settings_slug and row.gateway_controller
			else f"/app/payment-gateway/{row.name}"
		)
		gateways.append(
			{
				"name": row.gateway_controller or row.name,
				"route": route,
				"warnings": warnings,
				"healthy": not warnings,
			}
		)
	return gateways
