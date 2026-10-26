// Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
// License: MIT. See LICENSE

frappe.pages["payment-analytics"].on_page_load = function (wrapper) {
	new PaymentAnalytics(wrapper);
};

class PaymentAnalytics {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Payment Analytics"),
			single_column: true,
		});
		this.state = {
			range_key: "30",
			reference_doctype: null,
			recent_days: null,
			open_days: null,
			currency: null,
		};
		this.updating_filters = false;
		this.make_filters();
		this.$dashboard = $('<div class="payment-analytics-dashboard"></div>').appendTo(
			this.page.main
		);
		this.page.set_secondary_action(__("Refresh"), () => this.refresh());
		this.refresh();
	}

	make_filters() {
		this.range_filter = this.add_select(
			"range_key",
			__("Period"),
			[
				{ value: "today", label: __("Today") },
				{ value: "7", label: __("Last 7 days") },
				{ value: "30", label: __("Last 30 days") },
				{ value: "90", label: __("Last 90 days") },
				{ value: "all", label: __("All time") },
			],
			"30"
		);
		this.currency_filter = this.add_select("currency", __("Currency"), [""], "");
		this.doctype_filter = this.add_select(
			"reference_doctype",
			__("Reference Type"),
			[{ value: "", label: __("All reference types") }],
			""
		);
		this.recent_filter = this.add_select(
			"recent_days",
			__("Recent Payments"),
			[{ value: "", label: __("Same as period") }],
			""
		);
		this.open_filter = this.add_select(
			"open_days",
			__("Open Payments"),
			[{ value: "", label: __("Same as period") }],
			""
		);
	}

	add_select(fieldname, label, options, default_value) {
		let control;
		control = this.page.add_field({
			fieldname,
			label,
			fieldtype: "Select",
			options,
			default: default_value,
			change: () => {
				if (this.updating_filters) return;
				this.state[fieldname] = control.get_value() || null;
				this.refresh();
			},
		});
		return control;
	}

	refresh() {
		const request_id = (this.request_id || 0) + 1;
		this.request_id = request_id;
		this.page.set_indicator(__("Loading"), "orange");
		frappe
			.call({
				method: "payment_core.analytics.get_analytics",
				args: this.state,
			})
			.then(async (response) => {
				if (request_id !== this.request_id) return;
				this.data = response.message;
				this.state.range_key = this.data.range;
				this.state.reference_doctype = this.data.reference_doctype || null;
				this.state.recent_days = this.data.recent_days || null;
				this.state.open_days = this.data.open_days || null;
				this.state.currency = this.data.currency || null;
				await this.sync_filters();
				this.render();
				this.page.set_indicator(__("Updated"), "green");
			})
			.catch(() => {
				if (request_id === this.request_id) {
					this.page.set_indicator(__("Unable to load"), "red");
				}
			});
	}

	async sync_filters() {
		this.updating_filters = true;
		const updates = [];
		updates.push(
			this.set_select_options(
				this.currency_filter,
				(this.data.currencies || []).length
					? this.data.currencies.map((currency) => ({
							value: currency,
							label: currency,
					  }))
					: [{ value: "", label: __("No currency") }],
				this.state.currency || ""
			)
		);
		updates.push(
			this.set_select_options(
				this.doctype_filter,
				[{ value: "", label: __("All reference types") }].concat(
					(this.data.doctype_breakdown || []).map((row) => ({
						value: row.doctype,
						label: row.doctype,
					}))
				),
				this.state.reference_doctype || ""
			)
		);
		const window_options = [{ value: "", label: __("Same as period") }].concat(
			Object.entries(this.data.day_windows || this.data.ranges || {}).map(
				([value, label]) => ({
					value,
					label,
				})
			)
		);
		updates.push(
			this.set_select_options(
				this.recent_filter,
				window_options,
				this.state.recent_days || ""
			)
		);
		updates.push(
			this.set_select_options(this.open_filter, window_options, this.state.open_days || "")
		);
		updates.push(this.range_filter.set_value(this.state.range_key));
		await Promise.all(updates);
		this.updating_filters = false;
	}

	set_select_options(control, options, value) {
		control.df.options = options;
		control.refresh();
		return control.set_value(value);
	}

	render() {
		const data = this.data;
		const kpis = data.kpis || {};
		const context = [
			data.data_source
				? `<span>${__("Data source")}: <strong>${this.escape(
						data.data_source
				  )}</strong></span>`
				: "",
			data.reference_doctype
				? `<span>${__("Scoped to")}: <strong>${this.escape(
						data.reference_doctype
				  )}</strong></span>`
				: "",
		]
			.filter(Boolean)
			.join("");

		this.$dashboard.html(`
			${context ? `<div class="payment-analytics-context">${context}</div>` : ""}
			${this.render_mode_note(data.mode_note)}
			${this.render_warnings(data.health_warnings || [])}
			<div class="payment-kpi-grid">
				${this.kpi_card(__("Gross volume"), this.money(kpis.gross), __("Captured in range"))}
				${this.kpi_card(__("Successful payments"), kpis.successful || 0, __("Completed payments"))}
				${this.kpi_card(__("Customers"), kpis.customers || 0, __("Distinct buyers"))}
				${this.kpi_card(__("Average payment"), this.money(kpis.average), __("Per capture"))}
			</div>
			<div class="payment-chart-grid">
				${this.chart_card(__("Payments volume over time"), "payment-volume-chart")}
				${this.chart_card(__("Payment methods"), "payment-method-chart")}
			</div>
			${this.render_gateways(data.gateways || [])}
			${this.render_recent(data.recent || [])}
			${this.render_customers(data.top_customers || [])}
			<div class="payment-list-grid">
				${this.render_open(data.open_payments || [])}
				${this.render_failed(data.failed_payments || [])}
			</div>
		`);
		this.render_charts();
	}

	render_charts() {
		const volume_data = this.data.chart?.data;
		const volume_values = volume_data?.datasets?.[0]?.values || [];
		if (volume_data?.labels?.length && volume_values.some((value) => value)) {
			new frappe.Chart(this.$dashboard.find(".payment-volume-chart")[0], {
				data: volume_data,
				type: "line",
				height: 260,
				axisOptions: { xAxisMode: "tick", yAxisMode: "tick" },
				lineOptions: { regionFill: 1, spline: 1 },
				tooltipOptions: { formatTooltipY: (value) => this.money(value) },
			});
		} else {
			this.show_chart_empty(".payment-volume-chart", __("No captures in this range yet."));
		}

		const method_data = this.data.donut?.data;
		if (method_data?.labels?.length) {
			new frappe.Chart(this.$dashboard.find(".payment-method-chart")[0], {
				data: method_data,
				type: "donut",
				height: 260,
				tooltipOptions: { formatTooltipY: (value) => this.money(value) },
			});
		} else {
			this.show_chart_empty(
				".payment-method-chart",
				__("No payment methods in this range.")
			);
		}
	}

	show_chart_empty(selector, message) {
		this.$dashboard
			.find(selector)
			.html(`<div class="payment-empty">${this.escape(message)}</div>`);
	}

	kpi_card(label, value, hint) {
		return `<div class="payment-card payment-kpi">
			<div class="payment-kpi-label">${this.escape(label)}</div>
			<div class="payment-kpi-value">${this.escape(value)}</div>
			<div class="payment-muted">${this.escape(hint)}</div>
		</div>`;
	}

	chart_card(title, chart_class) {
		return `<div class="payment-card">
			<h3>${this.escape(title)}</h3>
			<div class="${chart_class}"></div>
		</div>`;
	}

	render_mode_note(note) {
		if (!note) return "";
		return `<div class="payment-card payment-info">
			<h3>${__("Gateway-only mode")}</h3>
			<p>${this.escape(note)}</p>
		</div>`;
	}

	render_warnings(warnings) {
		if (!warnings.length) return "";
		return `<div class="payment-card payment-warning">
			<h3>${__("Setup warnings")}</h3>
			<ul>${warnings.map((warning) => `<li>${this.escape(warning)}</li>`).join("")}</ul>
		</div>`;
	}

	render_gateways(gateways) {
		if (!gateways.length) return "";
		return `<div class="payment-card payment-section">
			<h3>${__("Gateways")}</h3>
			<div class="payment-gateway-grid">
				${gateways
					.map(
						(gateway) => `<div class="payment-gateway">
							${this.route_link(gateway.route, gateway.name)}
							<div class="payment-gateway-health">
								${
									gateway.healthy
										? `<span class="indicator-pill green">${__(
												"Healthy"
										  )}</span>`
										: (gateway.warnings || [])
												.map(
													(warning) =>
														`<div class="text-warning">${this.escape(
															warning
														)}</div>`
												)
												.join("")
								}
							</div>
						</div>`
					)
					.join("")}
			</div>
		</div>`;
	}

	render_recent(rows) {
		return this.table_card(
			__("Recent payments"),
			[__("Reference"), __("Buyer"), __("Amount"), __("Status"), __("When")],
			rows.map((row) => [
				this.route_link(
					row.route || `/app/payment-transaction/${encodeURIComponent(row.name)}`,
					`${row.reference_doctype || ""} · ${row.reference_docname || row.name}`
				),
				this.escape(row.buyer || "—"),
				this.money(row.amount, row.currency),
				this.status(row.status, row.badge),
				this.escape(row.when_display || "—"),
			]),
			__("No payments in this window.")
		);
	}

	render_customers(rows) {
		if (!rows.length) return "";
		return this.table_card(
			__("Top customers"),
			[__("Customer"), __("Type"), __("Captured"), __("Payments")],
			rows.map((row) => [
				this.escape(row.label || "—"),
				this.escape(row.customer_doctype || "—"),
				this.money(row.captured),
				this.escape(row.count || 0),
			]),
			""
		);
	}

	render_open(rows) {
		return this.table_card(
			__("Open payments"),
			[__("Reference"), __("Amount"), __("Status")],
			rows.map((row) => [
				this.route_link(
					row.route || `/app/payment-transaction/${encodeURIComponent(row.name)}`,
					row.reference_docname || row.name
				),
				this.money(row.amount, row.currency),
				this.status(row.status, "orange"),
			]),
			__("Nothing pending — all settled.")
		);
	}

	render_failed(rows) {
		return this.table_card(
			__("Failed payments"),
			[__("Reference"), __("Amount"), __("Reason")],
			rows.map((row) => [
				this.route_link(
					row.route || `/app/payment-transaction/${encodeURIComponent(row.name)}`,
					row.reference_docname || row.name
				),
				this.money(row.amount, row.currency),
				`<span class="text-danger">${this.escape(row.error_message || "—")}</span>`,
			]),
			__("No failed payments.")
		);
	}

	table_card(title, headers, rows, empty_message) {
		return `<div class="payment-card payment-section">
			<h3>${this.escape(title)}</h3>
			${
				rows.length
					? `<div class="payment-table-wrap"><table class="table table-bordered">
						<thead><tr>${headers.map((header) => `<th>${this.escape(header)}</th>`).join("")}</tr></thead>
						<tbody>${rows
							.map(
								(row) =>
									`<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`
							)
							.join("")}</tbody>
					</table></div>`
					: `<div class="payment-empty">${this.escape(empty_message)}</div>`
			}
		</div>`;
	}

	status(label, color) {
		return `<span class="indicator-pill ${this.escape(color || "gray")}">${this.escape(
			label || "—"
		)}</span>`;
	}

	route_link(route, label) {
		return `<a href="${this.escape(route || "#")}">${this.escape(label || "—")}</a>`;
	}

	money(value, currency) {
		return format_currency(value || 0, currency || this.state.currency);
	}

	escape(value) {
		return frappe.utils.escape_html(String(value ?? ""));
	}
}
