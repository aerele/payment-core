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
- ``purge_ledger`` (after_migrate / after_sync — after schema and fixture
  sync) removes any leftovers: doctypes with their tables and ledger-only
  Page/Report artifacts.

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
	# remove ledger doctype links from the Payment Core workspace so the
	# sidebar doesn't show links to doctypes that don't exist on this site
	_purge_workspace_ledger_links()
	frappe.logger().info(
		"payment_core gateway-only mode: %s", gateway_only_reason() or "own payment flow declared"
	)


def _purge_workspace_ledger_links():
	"""Remove workspace rows pointing at ledger artifacts on gateway-only sites.

	The workspace JSON is shared across all sites; on a gateway-only site the
	ledger doctypes don't exist, so their rows are dead. Removes links,
	shortcuts, cards and charts referencing purged doctypes (and the purged
	builder page) using direct DB deletes — a workspace save() would fail
	link validation against doctypes that no longer exist on this site.
	The desk sidebar itself needs no cleanup: it is computed from what the
	module actually holds, and the purged artifacts are already gone.
	"""
	ledger_set = list(LEDGER_DOCTYPES)
	if not frappe.db.exists("Workspace", "Payment Core"):
		return

	parent = "Payment Core"

	# links and shortcuts: remove rows whose link_to is a purged doctype or
	# the purged ledger page (Page-type links target it by name too)
	Link = frappe.qb.DocType("Workspace Link")
	frappe.qb.from_(Link).delete().where(
		(Link.parent == parent)
		& (Link.parenttype == "Workspace")
		& (
			Link.link_to.isin(ledger_set)
			| (Link.link_to == LEDGER_PAGE)
			| ((Link.link_type == "Report") & (Link.link_to == LEDGER_REPORT))
		)
	).run()
	# drop Card Break groups whose members were all purged (e.g. the home's
	# "Payment Ledger" card on an ERPNext site)
	link_rows = frappe.get_all(
		"Workspace Link",
		filters={"parent": parent, "parenttype": "Workspace"},
		fields=["name", "type"],
		order_by="idx asc",
	)
	# a group's members are the Link rows up to the next Card Break
	empty_breaks = []
	for position, row in enumerate(link_rows):
		if row.type != "Card Break":
			continue
		has_member = False
		for later in link_rows[position + 1 :]:
			if later.type == "Card Break":
				break
			if later.type == "Link":
				has_member = True
				break
		if not has_member:
			empty_breaks.append(row.name)
	if empty_breaks:
		frappe.db.delete("Workspace Link", {"name": ("in", empty_breaks), "parenttype": "Workspace"})

	Shortcut = frappe.qb.DocType("Workspace Shortcut")
	frappe.qb.from_(Shortcut).delete().where(
		(Shortcut.parent == parent)
		& (Shortcut.parenttype == "Workspace")
		& (
			((Shortcut.type == "DocType") & Shortcut.link_to.isin(ledger_set))
			| ((Shortcut.type == "Page") & (Shortcut.link_to == LEDGER_PAGE))
			| ((Shortcut.type == "Report") & (Shortcut.link_to == LEDGER_REPORT))
		)
	).run()

	# the home's "Payment Ledger" shortcut section (content blocks with a
	# payment-ledger- id prefix) references those rows: strip the section so
	# no orphan block is left behind on gateway-only sites
	content = frappe.db.get_value("Workspace", parent, "content")
	if content:
		blocks = frappe.parse_json(content) or []
		kept = [block for block in blocks if not str(block.get("id", "")).startswith("payment-ledger-")]
		if kept != blocks:
			frappe.db.set_value("Workspace", parent, "content", frappe.as_json(kept), update_modified=False)

	# number cards / charts whose document_type is a purged ledger doctype:
	# the workspace no longer ships any (the analytics custom block reports
	# across both modes), but sites upgraded from older versions may still
	# carry the rows and documents — drop them so nothing dead remains
	NumberCardRef = frappe.qb.DocType("Workspace Number Card")
	card_names = frappe.get_all("Number Card", filters={"document_type": ("in", ledger_set)}, pluck="name")
	if card_names:
		frappe.qb.from_(NumberCardRef).delete().where(
			(NumberCardRef.parent == parent)
			& (NumberCardRef.parenttype == "Workspace")
			& NumberCardRef.number_card_name.isin(card_names)
		).run()

	ChartRef = frappe.qb.DocType("Workspace Chart")
	chart_names = frappe.get_all(
		"Dashboard Chart", filters={"document_type": ("in", ledger_set)}, pluck="name"
	)
	if chart_names:
		frappe.qb.from_(ChartRef).delete().where(
			(ChartRef.parent == parent)
			& (ChartRef.parenttype == "Workspace")
			& ChartRef.chart_name.isin(chart_names)
		).run()
	# ... and the documents themselves: they query purged doctypes, so a
	# surviving card would error the moment it renders
	# (system context by design: migrate-time cleanup of standard artifacts)
	for name in card_names:
		frappe.delete_doc("Number Card", name, force=True, ignore_permissions=True)
	for name in chart_names:
		frappe.delete_doc("Dashboard Chart", name, force=True, ignore_permissions=True)

	# the curated standard Sidebar (current Frappe's sidebar mechanism) lists
	# ledger items too: on gateway-only sites remove rows pointing at purged
	# doctypes, the builder page and the ledger report, keeping the curated
	# order intact for everything that does exist here
	if frappe.db.exists("DocType", "Sidebar") and frappe.db.exists("Sidebar", "Payment Core"):
		SidebarItem = frappe.qb.DocType("Sidebar Item")
		frappe.qb.from_(SidebarItem).delete().where(
			(SidebarItem.parent == "Payment Core")
			& (SidebarItem.parenttype == "Sidebar")
			& (
				((SidebarItem.link_type == "DocType") & SidebarItem.link_to.isin(ledger_set))
				| ((SidebarItem.link_type == "Page") & (SidebarItem.link_to == LEDGER_PAGE))
				| ((SidebarItem.link_type == "Report") & (SidebarItem.link_to == LEDGER_REPORT))
			)
		).run()
		# drop section breaks whose group emptied out (e.g. "Reports" once
		# its only child, the settlement summary, is gone): a group's members
		# are the child=1 rows that follow it before the next top-level row
		rows = frappe.get_all(
			"Sidebar Item",
			filters={"parent": "Payment Core", "parenttype": "Sidebar"},
			fields=["name", "type", "child"],
			order_by="idx asc",
		)
		empty_sections = []
		for position, row in enumerate(rows):
			if row.type != "Section Break":
				continue
			has_member = False
			for later in rows[position + 1 :]:
				# a group ends at the next section break or the first
				# top-level (child=0) row, whichever comes first
				if later.type == "Section Break" or not later.child:
					break
				has_member = True
				break
			if not has_member:
				empty_sections.append(row.name)
		if empty_sections:
			frappe.db.delete("Sidebar Item", {"name": ("in", empty_sections), "parenttype": "Sidebar"})

	frappe.clear_cache(doctype="Workspace")


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
