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
		return `.payment-analytics-dashboard{display:flex;flex-direction:column;gap:1rem;padding:1rem 0;color:var(--ink-gray-9,#1f1f1f);font-family:var(--font-family,Inter,sans-serif)}
.payment-analytics-context{display:flex;flex-wrap:wrap;gap:1rem;color:var(--ink-gray-5,#6b7280);font-size:0.875rem}
.payment-card{padding:1rem;background:var(--surface-white,#fff);border:1px solid var(--outline-gray-modals,#e2e2e2);border-radius:0.75rem;box-shadow:var(--shadow-xs,0 1px 2px rgba(0,0,0,0.04))}
.payment-card h3{margin:0 0 0.5rem;font-size:0.9375rem;font-weight:600;color:var(--ink-gray-8,#333)}
.payment-card p,.payment-card ul{margin-bottom:0}
.payment-info{border-left:3px solid var(--blue-500,#0c85d0)}
.payment-warning{border-left:3px solid var(--amber-500,#df9311)}
.payment-kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:1rem}
.payment-kpi-label{color:var(--ink-gray-5,#6b7280);font-size:0.6875rem;font-weight:600;letter-spacing:0.05em;text-transform:uppercase}
.payment-kpi-value{margin:0.25rem 0;font-size:1.5rem;font-weight:700;color:var(--ink-gray-9,#1f1f1f)}
.payment-muted,.payment-empty{color:var(--ink-gray-5,#6b7280);font-size:0.8125rem}
.payment-empty{display:flex;align-items:center;justify-content:center;min-height:150px}
.payment-chart-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(240px,1fr);gap:1rem}
.payment-gateway-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:0.5rem}
.payment-gateway{padding:0.5rem;border:1px solid var(--outline-gray-modals,#e2e2e2);border-radius:0.5rem;background:var(--surface-white,#fff)}
.payment-gateway-health{margin-top:0.25rem;font-size:0.8125rem;color:var(--ink-gray-5)}
.payment-list-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem}
.payment-section{min-width:0}
.payment-table-wrap{overflow-x:auto}
.payment-table-wrap .table{margin-bottom:0;font-size:0.8125rem;width:100%;border-collapse:collapse}
.payment-table-wrap th{white-space:nowrap;padding:0.5rem 0.625rem;text-align:left;font-weight:500;color:var(--ink-gray-5,#6b7280);background:var(--surface-gray-2,#f3f3f3);border-bottom:1px solid var(--outline-gray-modals,#e2e2e2)}
.payment-table-wrap td{padding:0.5rem 0.625rem;border-bottom:1px solid var(--outline-gray-1,#f0f0f0);color:var(--ink-gray-8,#333)}
.payment-table-wrap tr:hover td{background:var(--surface-gray-1,#fafafa)}
.payment-table-wrap a{color:var(--blue-600,#0b6bcb);text-decoration:none}
.payment-table-wrap a:hover{text-decoration:underline}
.payment-collections-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(340px,1fr);gap:1rem}
.payment-calendar-bar{display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem}
.pc-cal-nav{border:1px solid var(--outline-gray-2,#d1d1d1);background:var(--surface-white,#fff);border-radius:0.375rem;padding:0.125rem 0.5rem;cursor:pointer;color:var(--ink-gray-7,#333);font-size:0.75rem}
.pc-cal-nav:hover{background:var(--surface-gray-2,#f3f3f3)}
.pc-cal-today{border:1px solid var(--outline-gray-2,#d1d1d1);background:var(--surface-white,#fff);border-radius:9999px;padding:0.125rem 0.75rem;cursor:pointer;font-size:0.6875rem;margin-left:0.375rem;color:var(--ink-gray-7,#333)}
.pc-cal-today:hover{background:var(--surface-gray-2,#f3f3f3)}
.payment-calendar-title{font-size:0.9375rem;font-weight:600;margin:0;color:var(--ink-gray-9)}
.payment-calendar{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:0.25rem}
.payment-calendar-dow{font-size:0.6875rem;font-weight:600;color:var(--ink-gray-4,#9ca3af);text-align:center;padding-bottom:0.125rem;text-transform:uppercase}
.payment-calendar-day{min-height:64px;padding:0.25rem 0.375rem;border:1px solid var(--outline-gray-1,#f0f0f0);border-radius:0.5rem;background:var(--surface-white,#fff);cursor:default;display:flex;flex-direction:column;gap:0.125rem;overflow:hidden}
.payment-calendar-day.has-dues{cursor:pointer}
.payment-calendar-day:hover.has-dues{border-color:var(--blue-400,#76bef9)}
.payment-calendar-day.selected{outline:2px solid var(--blue-500,#0c85d0);outline-offset:-2px}
.payment-calendar-day .pc-day-no{font-size:0.6875rem;color:var(--ink-gray-5,#6b7280)}
.payment-calendar-day.has-dues .pc-day-no{color:var(--ink-gray-9,#1f1f1f);font-weight:600}
.payment-calendar-day .pc-day-amt{font-size:0.6875rem;font-weight:600;color:var(--orange-600,#ca7e0c);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.payment-calendar-day .pc-day-cnt{font-size:0.6875rem;color:var(--ink-gray-5,#6b7280)}
.payment-calendar-day .pc-today{display:inline-block;background:var(--blue-500,#0c85d0);color:var(--surface-white,#fff);border-radius:9999px;padding:0 0.3125rem;font-size:0.625rem;margin-left:0.1875rem}
.pc-legend{display:flex;flex-wrap:wrap;gap:1rem;margin-top:0.5rem;color:var(--ink-gray-5,#6b7280);font-size:0.6875rem}
.pc-dot{display:inline-block;width:0.5rem;height:0.5rem;border-radius:9999px;margin-right:0.25rem;vertical-align:middle}
.pc-dot-selected{border:2px solid var(--blue-500,#0c85d0)}
.pc-dot-payable{background:var(--orange-500,#df9311)}
.pc-chips{display:flex;gap:0.25rem;margin-left:auto}
.pc-chip{border:1px solid var(--outline-gray-2,#d1d1d1);background:var(--surface-white,#fff);border-radius:9999px;padding:0.0625rem 0.75rem;font-size:0.6875rem;cursor:pointer;color:var(--ink-gray-6,#4b5563);font-weight:500}
.pc-chip:hover{background:var(--surface-gray-2,#f3f3f3)}
.pc-chip.active{background:var(--ink-gray-9,#1f1f1f);color:var(--surface-white,#fff);border-color:var(--ink-gray-9,#1f1f1f)}
.pc-upcoming-table{margin-bottom:0;font-size:0.75rem;table-layout:fixed;width:100%;border-collapse:collapse}
.pc-upcoming-table th{white-space:nowrap;font-size:0.6875rem;padding:0.375rem 0.5rem;text-align:left;font-weight:500;color:var(--ink-gray-5,#6b7280);background:var(--surface-gray-2,#f3f3f3);border-bottom:1px solid var(--outline-gray-modals,#e2e2e2)}
.pc-upcoming-table th:nth-child(1),.pc-upcoming-table td:nth-child(1){width:26%}
.pc-upcoming-table th:nth-child(2),.pc-upcoming-table td:nth-child(2){width:21%}
.pc-upcoming-table th:nth-child(3),.pc-upcoming-table td:nth-child(3){width:15%}
.pc-upcoming-table th:nth-child(4),.pc-upcoming-table td:nth-child(4){width:38%}
.pc-upcoming-table td{padding:0.375rem 0.5rem;border-bottom:1px solid var(--outline-gray-1,#f0f0f0);font-size:0.6875rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink-gray-8,#333)}
.pc-upcoming-table td:last-child,.pc-upcoming-table th:last-child{white-space:nowrap;text-align:right;font-weight:500}
.pc-upcoming-table td:first-child{white-space:nowrap}
.pc-date-link{color:var(--green-600,#078c55);text-decoration:none;font-weight:500}
.pc-date-link:hover{text-decoration:underline}
.payment-upcoming-row{display:flex;justify-content:space-between;gap:0.5rem;padding:0.375rem 0;border-bottom:1px solid var(--outline-gray-1,#f0f0f0);font-size:0.75rem;color:var(--ink-gray-7,#333)}
.payment-upcoming-row:last-child{border-bottom:0}
.payment-aging-bar{height:0.5rem;border-radius:9999px;background:var(--surface-gray-3,#e8e8e8);overflow:hidden;margin-top:0.25rem}
.payment-aging-fill{height:100%;background:var(--orange-500,#df9311);border-radius:9999px}
.payment-popup-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.3);display:flex;align-items:center;justify-content:center;z-index:2050;padding:1rem}
.payment-popup{background:var(--surface-white,#fff);border:1px solid var(--outline-gray-modals,#e2e2e2);border-radius:0.875rem;box-shadow:0 10px 30px rgba(0,0,0,0.15);min-width:420px;max-width:min(680px,92vw);max-height:80vh;overflow:auto;padding:1.25rem}
.payment-popup-head{display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;margin-bottom:0.5rem}
.payment-popup-close{border:1px solid var(--outline-gray-2,#d1d1d1);background:var(--surface-gray-2,#f3f3f3);color:var(--ink-gray-7,#333);border-radius:0.375rem;font-size:1rem;line-height:1;padding:0.25rem 0.625rem;cursor:pointer}
.payment-popup-close:hover{background:var(--surface-gray-3,#e8e8e8)}
.payment-tabs{display:flex;gap:1.25rem;border-bottom:1px solid var(--outline-gray-modals,#e2e2e2)}
.payment-tab{background:none;border:none;padding:0.5rem 0.125rem;font-size:0.9375rem;font-weight:600;color:var(--ink-gray-5,#6b7280);cursor:pointer;border-bottom:2px solid transparent;transition:color .15s,border-color .15s}
.payment-tab:hover{color:var(--ink-gray-7,#333)}
.payment-tab.active{color:var(--ink-gray-9,#1f1f1f);border-bottom-color:var(--ink-gray-9,#1f1f1f)}
.payment-kpi-red{border-top:3px solid var(--red-500,#e02424)}
.payment-kpi-red .payment-kpi-value{color:var(--red-600,#c62121)}
.payment-kpi-blue{border-color:var(--blue-500,#0c85d0)}
.payment-kpi-blue .payment-kpi-value{color:var(--blue-600,#0b6bcb)}
@media (max-width:800px){.payment-chart-grid,.payment-list-grid,.payment-collections-grid{grid-template-columns:1fr}}`;
	}
};
