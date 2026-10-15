# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

"""Keeps the shared ledger off gateway-only sites (ERPNext / own-flow apps).

Frappe syncs every module folder of every installed app, so suppression has
two halves:

- ``suppress_ledger_module`` (before_migrate, and from ``install.before_install``
  for the install itself — frappe reads ``before_app_install`` only from
  already-installed apps) drops the Payment Ledger module from the module map
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
	gateway_only_reason,
	is_gateway_only,
)


def suppress_ledger_module(app_name=None):
	"""Pre-sync half: stop the Payment Ledger module from being scanned.

	Also called from ``install.before_install``: frappe reads
	``before_app_install`` hooks only from apps that are already installed,
	so the app being installed must suppress itself from its own
	``before_install``.
	"""
	if app_name and app_name != "payment_core":
		return
	if not is_gateway_only():
		return
	# fail fast: a mode change that would drop payment history must abort
	# before any sync work runs, not only before the purge
	_raise_on_non_empty_ledger()
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
	# system context by design: migrate-time cleanup of standard artifacts
	for name in {LEDGER_REPORT, *frappe.get_all("Report", filters={"module": LEDGER_MODULE}, pluck="name")}:
		if frappe.db.exists("Report", name):
			frappe.delete_doc("Report", name, force=True, ignore_permissions=True)
	# system context by design: same for ledger module pages
	for name in {LEDGER_PAGE, *frappe.get_all("Page", filters={"module": LEDGER_MODULE}, pluck="name")}:
		if frappe.db.exists("Page", name):
			frappe.delete_doc("Page", name, force=True, ignore_permissions=True)
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
			data_holders.append(f"- {doctype} ({count} rows)")
	if not data_holders:
		return None
	frappe.throw(
		"\n".join(
			[
				_("Payment Core is in gateway-only mode, but the shared Payment Ledger still holds data:"),
				*data_holders,
				_("Migrating further would DROP these tables. To proceed safely:"),
				_("1. Take a backup: bench --site {0} backup --with-files").format(frappe.local.site),
				_(
					"2. Export any records you need (Payment Transaction / Payment Receipt list views support Export)"
				),
				_(
					"3. Then either set force_payment_ledger: 1 in site_config.json to keep the ledger, or remove the backed-up data so the cleanup can complete."
				),
			]
		),
		title=_("Payment Ledger data would be lost"),
	)
