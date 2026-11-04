// Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
// License: MIT
//
// Shared renderer for the Payment Analytics report. Consumed by the
// payment-analytics desk page and the workspace "Payment Analytics" custom
// block, so both surfaces render identical markup and cannot drift.
//
// Usage:
//   PaymentAnalyticsRender.render(container_element, data, { currency });
//   PaymentAnalyticsRender.draw_charts(container_element, data, { currency });
// `container` is a plain DOM element (works inside a shadow root).

window.PaymentAnalyticsRender = class PaymentAnalyticsRender {
	static esc(value) {
		return frappe.utils.escape_html(String(value == null ? "" : value));
	}

	static money(value, currency) {
		return format_currency(value || 0, currency);
	}

	static pill(label, color) {
		return `<span class="indicator-pill ${this.esc(color || "gray")}">${this.esc(
			label || "—"
		)}</span>`;
	}

	static link(route, label) {
		return `<a href="${this.esc(route || "#")}">${this.esc(label || "—")}</a>`;
	}

	static kpi_card(label, value, hint) {
		return `<div class="payment-card payment-kpi">
			<div class="payment-kpi-label">${this.esc(label)}</div>
			<div class="payment-kpi-value">${this.esc(value)}</div>
			<div class="payment-muted">${this.esc(hint)}</div>
		</div>`;
	}

	static chart_card(title, chart_class) {
		return `<div class="payment-card">
			<h3>${this.esc(title)}</h3>
			<div class="${chart_class}"></div>
		</div>`;
	}

	static table_card(title, headers, rows, empty_message) {
		return `<div class="payment-card payment-section">
			<h3>${this.esc(title)}</h3>
			${
				rows.length
					? `<div class="payment-table-wrap"><table class="table table-bordered">
						<thead><tr>${headers.map((h) => `<th>${this.esc(h)}</th>`).join("")}</tr></thead>
						<tbody>${rows
							.map(
								(row) =>
									`<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`
							)
							.join("")}</tbody>
					</table></div>`
					: `<div class="payment-empty">${this.esc(empty_message)}</div>`
			}
		</div>`;
	}

	static mode_note(note) {
		if (!note) return "";
		return `<div class="payment-card payment-info">
			<h3>${__("Gateway-only mode")}</h3>
			<p>${this.esc(note)}</p>
		</div>`;
	}

	static warnings(warn) {
		if (!warn.length) return "";
		return `<div class="payment-card payment-warning">
			<h3>${__("Setup warnings")}</h3>
			<ul>${warn.map((w) => `<li>${this.esc(w)}</li>`).join("")}</ul>
		</div>`;
	}

	static gateways(rows) {
		if (!rows.length) return "";
		return `<div class="payment-card payment-section">
			<h3>${__("Gateways")}</h3>
			<div class="payment-gateway-grid">
				${rows
					.map(
						(gateway) => `<div class="payment-gateway">
							${this.link(gateway.route, gateway.name)}
							<div class="payment-gateway-health">
								${
									gateway.healthy
										? `<span class="indicator-pill green">${__(
												"Healthy"
										  )}</span>`
										: (gateway.warnings || [])
												.map(
													(w) =>
														`<div class="text-warning">${this.esc(
															w
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

	static recent(rows, currency) {
		return this.table_card(
			__("Recent payments"),
			[__("Reference"), __("Buyer"), __("Amount"), __("Status"), __("When")],
			rows.map((row) => [
				this.link(
					row.route || `/app/payment-transaction/${encodeURIComponent(row.name)}`,
					`${row.reference_doctype || ""} · ${row.reference_docname || row.name}`
				),
				this.esc(row.buyer || "—"),
				this.money(row.amount, row.currency || currency),
				this.pill(row.status, row.badge),
				this.esc(row.when_display || "—"),
			]),
			__("No payments in this window.")
		);
	}

	static top_customers(rows, currency) {
		if (!rows.length) return "";
		return this.table_card(
			__("Top customers"),
			[__("Customer"), __("Type"), __("Captured"), __("Payments")],
			rows.map((row) => [
				this.esc(row.label || "—"),
				this.esc(row.customer_doctype || "—"),
				this.money(row.captured, currency),
				this.esc(row.count || 0),
			]),
			""
		);
	}

	static open_payments(rows, currency) {
		return this.table_card(
			__("Open payments"),
			[__("Reference"), __("Amount"), __("Status")],
			rows.map((row) => [
				this.link(
					row.route || `/app/payment-transaction/${encodeURIComponent(row.name)}`,
					row.reference_docname || row.name
				),
				this.money(row.amount, row.currency || currency),
				this.pill(row.status, "orange"),
			]),
			__("Nothing pending — all settled.")
		);
	}

	static failed_payments(rows, currency) {
		return this.table_card(
			__("Failed payments"),
			[__("Reference"), __("Amount"), __("Reason")],
			rows.map((row) => [
				this.link(
					row.route || `/app/payment-transaction/${encodeURIComponent(row.name)}`,
					row.reference_docname || row.name
				),
				this.money(row.amount, row.currency || currency),
				`<span class="text-danger">${this.esc(row.error_message || "—")}</span>`,
			]),
			__("No failed payments.")
		);
	}

	static render(container, data, opts = {}) {
		const currency = opts.currency;
		const kpis = data.kpis || {};
		const context = [
			data.data_source
				? `<span>${__("Data source")}: <strong>${this.esc(
						data.data_source
				  )}</strong></span>`
				: "",
			data.reference_doctype
				? `<span>${__("Scoped to")}: <strong>${this.esc(
						data.reference_doctype
				  )}</strong></span>`
				: "",
		]
			.filter(Boolean)
			.join("");

		container.innerHTML = `
			${context ? `<div class="payment-analytics-context">${context}</div>` : ""}
			${this.mode_note(data.mode_note)}
			${this.warnings(data.health_warnings || [])}
			<div class="payment-kpi-grid">
				${this.kpi_card(__("Gross volume"), this.money(kpis.gross, currency), __("Captured in range"))}
				${this.kpi_card(__("Successful payments"), kpis.successful || 0, __("Completed payments"))}
				${this.kpi_card(__("Customers"), kpis.customers || 0, __("Distinct buyers"))}
				${this.kpi_card(__("Average payment"), this.money(kpis.average, currency), __("Per capture"))}
			</div>
			<div class="payment-chart-grid">
				${this.chart_card(__("Payments volume over time"), "payment-volume-chart")}
				${this.chart_card(__("Payment methods"), "payment-method-chart")}
			</div>
			${this.gateways(data.gateways || [])}
			${this.recent(data.recent || [], currency)}
			${this.top_customers(data.top_customers || [], currency)}
			<div class="payment-list-grid">
				${this.open_payments(data.open_payments || [], currency)}
				${this.failed_payments(data.failed_payments || [], currency)}
			</div>
		`;

		this.draw_charts(container, data, opts);
	}

	static draw_charts(container, data, opts = {}) {
		const currency = opts.currency;
		const volume_data = data.chart && data.chart.data;
		const first_set =
			volume_data && volume_data.datasets && volume_data.datasets[0]
				? volume_data.datasets[0].values || []
				: [];
		if (
			volume_data &&
			volume_data.labels &&
			volume_data.labels.length &&
			first_set.some((v) => v)
		) {
			new frappe.Chart(container.querySelector(".payment-volume-chart"), {
				data: volume_data,
				type: "line",
				height: 260,
				axisOptions: { xAxisMode: "tick", yAxisMode: "tick" },
				lineOptions: { regionFill: 1, spline: 1 },
				tooltipOptions: { formatTooltipY: (value) => this.money(value, currency) },
			});
		} else {
			container.querySelector(
				".payment-volume-chart"
			).innerHTML = `<div class="payment-empty">${__(
				"No captures in this range yet."
			)}</div>`;
		}

		const method_data = data.donut && data.donut.data;
		if (method_data && method_data.labels && method_data.labels.length) {
			new frappe.Chart(container.querySelector(".payment-method-chart"), {
				data: method_data,
				type: "donut",
				height: 260,
				tooltipOptions: { formatTooltipY: (value) => this.money(value, currency) },
			});
		} else {
			container.querySelector(
				".payment-method-chart"
			).innerHTML = `<div class="payment-empty">${__(
				"No payment methods in this range."
			)}</div>`;
		}
	}

	static style() {
		// Shared card/grid/table styling. The desk page loads this through
		// payment_analytics.css; the custom block inlines the same rules in
		// its own <style> because shadow roots cannot reach app stylesheets.
		return `.payment-analytics-dashboard{display:flex;flex-direction:column;gap:var(--margin-md);padding:var(--padding-md) 0;color:var(--text-color)}
.payment-analytics-context{display:flex;flex-wrap:wrap;gap:var(--margin-md);color:var(--text-muted);font-size:var(--text-sm)}
.payment-card{padding:var(--padding-md);background:var(--card-bg);border:1px solid var(--border-color);border-radius:var(--border-radius);box-shadow:var(--shadow-xs)}
.payment-card h3{margin:0 0 var(--margin-sm);font-size:var(--text-md);font-weight:var(--weight-semibold)}
.payment-card p,.payment-card ul{margin-bottom:0}
.payment-info{border-left:3px solid var(--blue-500)}
.payment-warning{border-left:3px solid var(--orange-500)}
.payment-kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:var(--margin-md)}
.payment-kpi-label{color:var(--text-muted);font-size:var(--text-xs);font-weight:var(--weight-semibold);letter-spacing:0.04em;text-transform:uppercase}
.payment-kpi-value{margin:var(--margin-xs) 0;font-size:var(--text-2xl);font-weight:var(--weight-bold)}
.payment-muted,.payment-empty{color:var(--text-muted);font-size:var(--text-sm)}
.payment-empty{display:flex;align-items:center;justify-content:center;min-height:160px}
.payment-chart-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(260px,1fr);gap:var(--margin-md)}
.payment-gateway-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:var(--margin-sm)}
.payment-gateway{padding:var(--padding-sm);border:1px solid var(--border-color);border-radius:var(--border-radius)}
.payment-gateway-health{margin-top:var(--margin-xs);font-size:var(--text-sm)}
.payment-list-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:var(--margin-md)}
.payment-section{min-width:0}
.payment-table-wrap{overflow-x:auto}
.payment-table-wrap .table{margin-bottom:0;font-size:var(--text-sm)}
.payment-table-wrap th{white-space:nowrap}
@media (max-width:800px){.payment-chart-grid,.payment-list-grid{grid-template-columns:1fr}}`;
	}
};
