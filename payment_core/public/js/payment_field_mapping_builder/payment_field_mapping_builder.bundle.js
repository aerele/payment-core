import { createApp } from "vue";
import PaymentFieldMappingBuilderApp from "./PaymentFieldMappingBuilder.vue";

class PaymentFieldMappingVisualBuilder {
	constructor({ wrapper, page, reference_doctype }) {
		this.wrapper = wrapper;
		this.page = page;
		this.reference_doctype = reference_doctype || "";
		this.app = null;
		this.component = null;
		this.setup_page();
		this.mount();
	}

	setup_page() {
		this.page.set_title(__("Payment Field Mapping"));
		this.page.clear_actions();
		this.page.clear_menu();
		this.page.clear_custom_actions();

		this.primary_button = this.page.set_primary_action(__("Save Mapping"), () =>
			this.component?.save()
		);
		this.reset_button = this.page.add_button(__("Reset Changes"), () =>
			this.component?.reset()
		);
		this.page.add_menu_item(__("Open Stored Mappings"), () =>
			frappe.set_route("List", "Payment Field Mapping")
		);

		this.update_page({
			can_save: false,
			dirty: false,
			loading: false,
			status: __("Select a reference DocType"),
			color: "orange",
		});
	}

	mount() {
		this.app = createApp(PaymentFieldMappingBuilderApp, {
			initialDoctype: this.reference_doctype,
			updatePage: (state) => this.update_page(state),
		});
		SetVueGlobals(this.app);
		this.component = this.app.mount(this.wrapper.get(0));
	}

	update_page({ can_save, dirty, loading, status, color }) {
		this.primary_button?.prop("disabled", loading || !can_save || !dirty);
		this.reset_button?.prop("disabled", loading || !dirty);
		if (status) {
			this.page.set_indicator(status, color || "gray");
		}
	}

	destroy() {
		this.app?.unmount();
		this.app = null;
		this.component = null;
	}
}

frappe.provide("payment_core.ui");
window.payment_core.ui.PaymentFieldMappingVisualBuilder = PaymentFieldMappingVisualBuilder;

export default PaymentFieldMappingVisualBuilder;
