# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Keeps the shared ledger off gateway-only sites (ERPNext / own-flow apps).

Frappe syncs every module folder of every installed app, so suppression has
two halves:

- ``suppress_ledger_module`` (before_migrate / before_app_install — both run
  before schema sync) drops the Payment Ledger module from the module map
  frappe is about to walk, so the ledger doctypes are never created or
  updated on such sites.
- ``purge_ledger`` (after_migrate / after_sync — after schema, fixtures and
  workspace sync) removes any leftovers: doctypes with their tables and the
  ledger workspace links. Analytics stay everywhere — they adapt to the
  site's own payment flow (see analytics_adapters) — so the dashboard block
  and the Payment Analytics shortcut are intentionally kept on gateway-only
  sites.

Both halves are idempotent and no-ops on full-ledger sites.
"""

import frappe
from frappe import _

from payment_core.mode import (
	LEDGER_DOCTYPES,
	LEDGER_MODULE,
	LEDGER_PAGE,
	LEDGER_REPORT,
	LEDGER_SHORTCUT_LABELS,
	LEDGER_SIDEBAR_LABELS,
	gateway_only_reason,
	is_gateway_only,
)


def suppress_ledger_module(app_name=None):
	"""Pre-sync half: stop the Payment Ledger module from being scanned."""
	if app_name and app_name != "payment_core":
		return
	if not is_gateway_only():
		return
	# the module map holds scrubbed names (payment_ledger)
	modules = frappe.local.app_modules.get("payment_core") or []
	scrubbed = frappe.scrub(LEDGER_MODULE)
	if scrubbed in modules:
		modules.remove(scrubbed)


def purge_ledger():
	"""Post-sync half: remove leftovers when running gateway-only."""
	if not is_gateway_only():
		return
	# raises before any drop when payment history exists
	_raise_on_non_empty_ledger()
	for doctype in LEDGER_DOCTYPES:
		if frappe.db.exists("DocType", doctype):
			frappe.delete_doc("DocType", doctype, force=True, ignore_permissions=True)
		elif frappe.db.table_exists(doctype):
			# drop orphan tables left by an install race so the site converges
			frappe.db.sql_ddl(
				f"drop table if exists `tab{doctype}`"
			)  # nosemgrep: python.lang.security.audit.formatted-sql-query.unsafe
	for name in {LEDGER_REPORT, *frappe.get_all("Report", filters={"module": LEDGER_MODULE}, pluck="name")}:
		if frappe.db.exists("Report", name):
			frappe.db.delete("Report", name)
	for name in {LEDGER_PAGE, *frappe.get_all("Page", filters={"module": LEDGER_MODULE}, pluck="name")}:
		if frappe.db.exists("Page", name):
			frappe.db.delete("Page", name)
	_strip_ledger_workspace_links()
	# deletions must be durable before later migrate phases / the next request
	frappe.db.commit()  # nosemgrep: rules.frappe-manual-commit
	frappe.logger().info(
		"payment_core gateway-only mode: %s", gateway_only_reason() or "own payment flow declared"
	)


def _raise_on_non_empty_ledger():
	"""Never silently destroy payment history: block the purge when data exists.

	Returns None when every ledger table is empty or absent (purge may
	proceed); raises otherwise, telling the admin how to keep their data.
	Docs deleted with the DocType are irrecoverable, so this is a hard stop.
	"""
	data_holders = []
	for doctype in LEDGER_DOCTYPES:
		if not frappe.db.table_exists(doctype):
			continue
		try:
			count = frappe.db.count(doctype)
		except Exception as exc:
			# only a missing table counts as absent; any other DB error must re-raise (data-loss guard)
			if not frappe.db.is_table_missing(exc):
				raise
			count = 0
		if count:
			data_holders.append(f"{doctype} ({count} rows)")
	if not data_holders:
		return None
	frappe.throw(
		_(
			"Payment Core is in gateway-only mode, but the shared Payment Ledger still holds data: {0}. "
			"Migrating further would DROP these tables. To keep the data, either set "
			"force_payment_ledger: 1 in site_config.json, or take a backup and export the records "
			"before removing the app that owns this site's payment flow."
		).format("<br>• " + "<br>• ".join(data_holders)),
		title=_("Payment Ledger data would be lost"),
	)


def _strip_ledger_workspace_links():
	"""Drop ledger sidebar items/shortcuts from the Payment Core workspace."""
	workspace = frappe.db.exists("Workspace", "Payment Core")
	if not workspace:
		return
	frappe.db.delete(
		"Workspace Sidebar Item",
		{"parent": workspace, "parenttype": "Workspace", "label": ("in", LEDGER_SIDEBAR_LABELS)},
	)
	frappe.db.delete(
		"Workspace Shortcut",
		{"parent": workspace, "parenttype": "Workspace", "label": ("in", LEDGER_SHORTCUT_LABELS)},
	)
