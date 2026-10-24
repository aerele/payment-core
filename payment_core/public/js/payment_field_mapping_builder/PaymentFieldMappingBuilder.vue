<script setup>
import { Background } from "@vue-flow/background";
import { Panel, PanelPosition, VueFlow, useVueFlow } from "@vue-flow/core";
import { computed, nextTick, onMounted, ref, watchEffect } from "vue";

import FieldNode from "./components/FieldNode.vue";
import MappingEdge from "./components/MappingEdge.vue";
import PurposeNode from "./components/PurposeNode.vue";

const DEFAULT_PURPOSES = [
	["amount", "Amount", ["Currency", "Float", "Int"]],
	["currency", "Currency", ["Link", "Data", "Select"]],
	["payment_method", "Payment Method", ["Select", "Data", "Link"]],
	["customer_email", "Customer Email", ["Data", "Small Text"]],
	["customer", "Customer", ["Link", "Dynamic Link"]],
	["payer_name", "Payer Name", ["Data", "Small Text"]],
	["order_id", "Order ID", ["Data", "Int", "Small Text"]],
	["due_date", "Due Date", ["Date", "Datetime"]],
	["payment_channel", "Payment Channel", ["Select", "Data"]],
	["phone_number", "Phone Number", ["Data", "Phone", "Small Text"]],
].map(([purpose, label, fieldtypes]) => ({ purpose, label, fieldtypes }));

const props = defineProps({
	initialDoctype: {
		type: String,
		default: "",
	},
	updatePage: {
		type: Function,
		required: true,
	},
});

const { fitView, zoomIn, zoomOut } = useVueFlow();

const doctypeControlRoot = ref(null);
const disabledControlRoot = ref(null);
const elements = ref([]);
const purposes = ref(DEFAULT_PURPOSES);
const fields = ref([]);
const referenceDoctype = ref("");
const disabled = ref(false);
const mappingName = ref("");
const loading = ref(false);
const selectedPurpose = ref("");
const searchTerm = ref("");
const baseStatus = ref(__("Select a reference DocType"));
const baseColor = ref("orange");
const savedState = ref({ disabled: false, mapping: [] });

let doctypeControl = null;
let disabledControl = null;
let requestId = 0;
let syncingControls = false;

const graphEdges = computed(() => elements.value.filter((element) => element.source));
const graphNodes = computed(() => elements.value.filter((element) => !element.source));
const fieldNodes = computed(() =>
	graphNodes.value.filter((node) => node.type === "referenceField")
);

const mappingRows = computed(() => {
	const edgesByPurpose = new Map(
		graphEdges.value.map((edge) => [edge.data.purpose, edge.data.reference_field])
	);
	return purposes.value
		.map((purpose) => ({
			purpose: purpose.purpose,
			reference_field: edgesByPurpose.get(purpose.purpose) || "",
		}))
		.filter((row) => row.reference_field);
});

const persistentState = computed(() => ({
	disabled: Boolean(disabled.value),
	mapping: normalizeMapping(mappingRows.value),
}));

const dirty = computed(
	() => JSON.stringify(persistentState.value) !== JSON.stringify(savedState.value)
);
const hasAmountMapping = computed(() => mappingRows.value.some((row) => row.purpose === "amount"));
const canSave = computed(
	() => Boolean(referenceDoctype.value) && hasAmountMapping.value && !loading.value
);

const selectedPurposeDefinition = computed(() =>
	purposes.value.find((purpose) => purpose.purpose === selectedPurpose.value)
);

const visibleFields = computed(() => {
	const added = new Set(fieldNodes.value.map((node) => node.data.fieldname));
	const query = searchTerm.value.trim().toLowerCase();
	const acceptedTypes = selectedPurposeDefinition.value?.fieldtypes || [];

	return fields.value.filter((field) => {
		if (added.has(field.fieldname)) return false;
		if (acceptedTypes.length && !acceptedTypes.includes(field.fieldtype)) return false;
		const label = (field.label || field.fieldname).toLowerCase();
		return !query || label.includes(query) || field.fieldname.toLowerCase().includes(query);
	});
});

watchEffect(() => {
	let status = baseStatus.value;
	let color = baseColor.value;

	if (loading.value) {
		status = __("Loading mapping");
		color = "blue";
	} else if (!referenceDoctype.value) {
		status = __("Select a reference DocType");
		color = "orange";
	} else if (dirty.value && !hasAmountMapping.value) {
		status = __("Amount mapping is required");
		color = "red";
	} else if (dirty.value) {
		status = __("Unsaved changes");
		color = "orange";
	}

	props.updatePage({
		can_save: canSave.value,
		dirty: dirty.value,
		loading: loading.value,
		status,
		color,
	});
});

function normalizeMapping(rows) {
	const purposeOrder = new Map(purposes.value.map((purpose, index) => [purpose.purpose, index]));
	return [...rows]
		.filter((row) => row.purpose && row.reference_field)
		.map((row) => ({
			purpose: row.purpose,
			reference_field: row.reference_field,
		}))
		.sort(
			(left, right) =>
				(purposeOrder.get(left.purpose) ?? 999) - (purposeOrder.get(right.purpose) ?? 999)
		);
}

function purposeNodeId(purpose) {
	return "purpose-" + purpose;
}

function fieldNodeId(fieldname) {
	return "field-" + fieldname;
}

function mappingEdgeId(purpose) {
	return "mapping-" + purpose;
}

function purposeNodes() {
	return purposes.value.map((purpose, index) => ({
		id: purposeNodeId(purpose.purpose),
		type: "purpose",
		position: { x: 80, y: 65 + index * 88 },
		data: {
			...purpose,
			required: purpose.purpose === "amount",
		},
		draggable: false,
	}));
}

function makeFieldNode(field, missing = false) {
	return {
		id: fieldNodeId(field.fieldname),
		type: "referenceField",
		position: { x: 620, y: 65 },
		data: {
			fieldname: field.fieldname,
			label: field.label || field.fieldname,
			fieldtype: field.fieldtype || "",
			missing,
		},
		draggable: false,
	};
}

function makeEdge(purpose, referenceField) {
	return {
		id: mappingEdgeId(purpose),
		type: "mapping",
		source: purposeNodeId(purpose),
		sourceHandle: "purpose-output",
		target: fieldNodeId(referenceField),
		targetHandle: "field-input",
		data: {
			purpose,
			reference_field: referenceField,
		},
		markerEnd: {
			type: "arrow",
			width: 15,
			height: 15,
			strokeWidth: 1.5,
			color: "#687178",
		},
	};
}

function hydrateGraph(mapping) {
	const fieldByName = new Map(fields.value.map((field) => [field.fieldname, field]));
	const mappedFieldNames = [...new Set(mapping.map((row) => row.reference_field))];
	const mappedFields = mappedFieldNames.map((fieldname) => {
		const field = fieldByName.get(fieldname);
		return makeFieldNode(field || { fieldname, fieldtype: "", label: fieldname }, !field);
	});
	const edges = mapping.map((row) => makeEdge(row.purpose, row.reference_field));

	elements.value = [...purposeNodes(), ...mappedFields, ...edges];
	selectedPurpose.value = "";
	applyFixedLayout();
	fitGraph();
}

function applyFixedLayout() {
	const nodes = graphNodes.value;
	const edges = graphEdges.value;
	const purposeOrder = new Map(purposes.value.map((purpose, index) => [purpose.purpose, index]));
	const fieldPriority = new Map();

	for (const edge of edges) {
		const priority = purposeOrder.get(edge.data.purpose) ?? 999;
		const current = fieldPriority.get(edge.data.reference_field);
		fieldPriority.set(
			edge.data.reference_field,
			current === undefined ? priority : Math.min(current, priority)
		);
	}

	const sortedFields = nodes
		.filter((node) => node.type === "referenceField")
		.sort((left, right) => {
			const priorityDifference =
				(fieldPriority.get(left.data.fieldname) ?? 999) -
				(fieldPriority.get(right.data.fieldname) ?? 999);
			return priorityDifference || left.data.fieldname.localeCompare(right.data.fieldname);
		});

	const fieldPositions = new Map(
		sortedFields.map((node, index) => [node.id, { x: 620, y: 65 + index * 88 }])
	);

	elements.value = elements.value.map((element) => {
		if (element.source) return element;
		if (element.type === "purpose") {
			const index = purposeOrder.get(element.data.purpose) ?? 0;
			return { ...element, position: { x: 80, y: 65 + index * 88 } };
		}
		return { ...element, position: fieldPositions.get(element.id) };
	});
}

function fitGraph() {
	nextTick(() => {
		window.setTimeout(() => fitView({ padding: 0.15, duration: 250 }), 0);
	});
}

function syncDoctypeControl(value) {
	syncingControls = true;
	doctypeControl?.set_input(value || "");
	window.setTimeout(() => {
		syncingControls = false;
	}, 0);
}

function syncDisabledControl(value) {
	syncingControls = true;
	disabled.value = Boolean(value);
	disabledControl?.set_input(value ? 1 : 0);
	window.setTimeout(() => {
		syncingControls = false;
	}, 0);
}

function confirmDiscard() {
	return new Promise((resolve) => {
		frappe.confirm(
			__("Discard the unsaved mapping changes?"),
			() => resolve(true),
			() => resolve(false)
		);
	});
}

async function handleDoctypeChange() {
	if (syncingControls) return;

	const nextDoctype = doctypeControl.get_value() || "";
	const previousDoctype = referenceDoctype.value;
	if (nextDoctype === previousDoctype) return;

	if (dirty.value && !(await confirmDiscard())) {
		syncDoctypeControl(previousDoctype);
		return;
	}

	await loadData(nextDoctype, previousDoctype);
}

async function loadData(doctype, previousDoctype = referenceDoctype.value) {
	const currentRequest = ++requestId;

	if (!doctype) {
		referenceDoctype.value = "";
		fields.value = [];
		mappingName.value = "";
		purposes.value = DEFAULT_PURPOSES;
		syncDisabledControl(false);
		savedState.value = { disabled: false, mapping: [] };
		baseStatus.value = __("Select a reference DocType");
		baseColor.value = "orange";
		hydrateGraph([]);
		return;
	}

	loading.value = true;
	try {
		const data = await frappe.xcall("payment_core.field_mapping.get_mapping_builder_data", {
			doctype,
		});
		if (currentRequest !== requestId) return;

		referenceDoctype.value = data.reference_doctype || doctype;
		purposes.value = data.purposes?.length ? data.purposes : DEFAULT_PURPOSES;
		fields.value = data.fields || [];
		mappingName.value = data.mapping_name || "";
		syncDoctypeControl(referenceDoctype.value);
		syncDisabledControl(data.disabled);
		const mapping = normalizeMapping(data.mapping || []);
		savedState.value = {
			disabled: Boolean(data.disabled),
			mapping,
		};
		baseStatus.value = data.mapping_name
			? __("Stored mapping loaded")
			: __("Not configured yet");
		baseColor.value = data.mapping_name ? "green" : "orange";
		hydrateGraph(mapping);
	} catch (error) {
		if (currentRequest === requestId) {
			syncDoctypeControl(previousDoctype);
		}
		throw error;
	} finally {
		if (currentRequest === requestId) loading.value = false;
	}
}

function addField(fieldname) {
	if (!referenceDoctype.value || loading.value) return;
	if (fieldNodes.value.some((node) => node.data.fieldname === fieldname)) return;

	const field = fields.value.find((candidate) => candidate.fieldname === fieldname);
	if (!field) return;

	elements.value = [...elements.value, makeFieldNode(field)];
	applyFixedLayout();
	fitGraph();
}

function startFieldDrag(event, fieldname) {
	event.dataTransfer?.setData("application/payment-field", fieldname);
	if (event.dataTransfer) event.dataTransfer.effectAllowed = "copy";
}

function handleDragOver(event) {
	event.preventDefault();
	if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
}

function handleDrop(event) {
	event.preventDefault();
	const fieldname = event.dataTransfer?.getData("application/payment-field");
	if (fieldname) addField(fieldname);
}

function selectPurpose(purpose) {
	selectedPurpose.value = selectedPurpose.value === purpose ? "" : purpose;
}

function connectNodes(connection) {
	const purposeNode = graphNodes.value.find((node) => node.id === connection.source);
	const fieldNode = graphNodes.value.find((node) => node.id === connection.target);

	if (purposeNode?.type !== "purpose" || fieldNode?.type !== "referenceField") {
		frappe.throw({
			title: __("Invalid mapping"),
			message: __("Connect a payment purpose to a reference field."),
		});
	}

	if (
		fieldNode.data.missing ||
		!purposeNode.data.fieldtypes.includes(fieldNode.data.fieldtype)
	) {
		frappe.throw({
			title: __("Incompatible field"),
			message: __("{0} cannot be mapped to {1}.", [
				frappe.utils.escape_html(fieldNode.data.label),
				__(purposeNode.data.label),
			]),
		});
	}

	const edge = makeEdge(purposeNode.data.purpose, fieldNode.data.fieldname);
	elements.value = [
		...elements.value.filter(
			(element) => !element.source || element.data.purpose !== purposeNode.data.purpose
		),
		edge,
	];
	applyFixedLayout();
}

function removeEdge(edgeId) {
	elements.value = elements.value.filter((element) => element.id !== edgeId);
	applyFixedLayout();
}

function removeField(nodeId) {
	const node = graphNodes.value.find((candidate) => candidate.id === nodeId);
	if (!node) return;

	const connected = graphEdges.value.some(
		(edge) => edge.source === nodeId || edge.target === nodeId
	);
	const performRemoval = () => {
		elements.value = elements.value.filter(
			(element) =>
				element.id !== nodeId && element.source !== nodeId && element.target !== nodeId
		);
		applyFixedLayout();
	};

	if (!connected) {
		performRemoval();
		return;
	}

	frappe.confirm(
		__("Remove {0} and all of its mappings?", [frappe.bold(node.data.label)]),
		performRemoval
	);
}

async function save() {
	if (!referenceDoctype.value) {
		frappe.throw(__("Select a reference DocType first."));
	}
	if (!hasAmountMapping.value) {
		frappe.throw(__("Connect Amount to a reference field before saving."));
	}
	if (!dirty.value || loading.value) return;

	loading.value = true;
	try {
		const result = await frappe.xcall("payment_core.field_mapping.save_mapping_builder_data", {
			reference_doctype: referenceDoctype.value,
			mapping: mappingRows.value,
			disabled: disabled.value ? 1 : 0,
		});
		mappingName.value = result.name;
		syncDisabledControl(result.disabled);
		const mapping = normalizeMapping(result.mapping || mappingRows.value);
		savedState.value = {
			disabled: Boolean(result.disabled),
			mapping,
		};
		baseStatus.value = __("Mapping saved");
		baseColor.value = "green";
		hydrateGraph(mapping);
		frappe.show_alert({
			message: __("Payment field mapping saved"),
			indicator: "green",
		});
	} finally {
		loading.value = false;
	}
}

function reset() {
	syncDisabledControl(savedState.value.disabled);
	hydrateGraph(savedState.value.mapping);
	baseStatus.value = mappingName.value ? __("Stored mapping loaded") : __("Not configured yet");
	baseColor.value = mappingName.value ? "green" : "orange";
}

onMounted(() => {
	doctypeControl = frappe.ui.form.make_control({
		parent: $(doctypeControlRoot.value),
		df: {
			label: __("Reference DocType"),
			fieldname: "reference_doctype",
			fieldtype: "Link",
			options: "DocType",
			reqd: 1,
			get_query: () => ({ filters: { istable: 0, issingle: 0 } }),
			change: handleDoctypeChange,
		},
		render_input: true,
	});

	disabledControl = frappe.ui.form.make_control({
		parent: $(disabledControlRoot.value),
		df: {
			label: __("Disabled"),
			fieldname: "disabled",
			fieldtype: "Check",
			change: () => {
				if (!syncingControls) {
					disabled.value = Boolean(disabledControl.get_value());
				}
			},
		},
		render_input: true,
	});

	syncDoctypeControl(props.initialDoctype);
	hydrateGraph([]);
	if (props.initialDoctype) {
		loadData(props.initialDoctype, "");
	}
});

defineExpose({ reset, save });
</script>

<template>
	<div class="payment-mapping-visual-builder">
		<aside class="mapping-sidebar">
			<div class="sidebar-heading">
				<h4>{{ __("Mapping Details") }}</h4>
				<p>
					{{
						__("Choose a DocType, add its fields, then connect each payment purpose.")
					}}
				</p>
			</div>

			<div ref="doctypeControlRoot" class="doctype-control"></div>
			<div ref="disabledControlRoot" class="disabled-control"></div>

			<div class="sidebar-divider"></div>

			<div class="field-palette-heading">
				<div>
					<h5>{{ __("Reference Fields") }}</h5>
					<p v-if="selectedPurposeDefinition">
						{{ __("Compatible with {0}", [__(selectedPurposeDefinition.label)]) }}
					</p>
					<p v-else>{{ __("Select a purpose to filter compatible fields.") }}</p>
				</div>
				<button
					v-if="selectedPurpose"
					type="button"
					class="btn btn-xs btn-default"
					@click="selectedPurpose = ''"
				>
					{{ __("Show all") }}
				</button>
			</div>

			<div class="field-search">
				<span v-html="frappe.utils.icon('search', 'sm')"></span>
				<input
					v-model="searchTerm"
					type="search"
					class="form-control input-xs"
					:placeholder="__('Search fields')"
					:disabled="!referenceDoctype || loading"
				/>
			</div>

			<div class="field-palette">
				<div v-if="!referenceDoctype" class="palette-empty">
					{{ __("Select a reference DocType to load its fields.") }}
				</div>
				<div v-else-if="!visibleFields.length" class="palette-empty">
					{{ __("No available fields match this filter.") }}
				</div>
				<div
					v-for="field in visibleFields"
					:key="field.fieldname"
					class="field-palette-item"
					draggable="true"
					@dragstart="startFieldDrag($event, field.fieldname)"
				>
					<span class="drag-icon" v-html="frappe.utils.icon('drag', 'sm')"></span>
					<span class="palette-field-name">{{ field.label || field.fieldname }}</span>
					<button
						type="button"
						class="btn btn-xs btn-default"
						@click="addField(field.fieldname)"
					>
						{{ __("Add") }}
					</button>
				</div>
			</div>
		</aside>

		<section class="mapping-canvas" @dragover="handleDragOver" @drop="handleDrop">
			<div v-if="loading" class="loading-overlay">
				<span class="loading-text">{{ __("Loading mapping...") }}</span>
			</div>
			<VueFlow
				v-model="elements"
				:nodes-draggable="false"
				:nodes-connectable="Boolean(referenceDoctype) && !loading"
				:edges-updatable="false"
				:delete-key-code="null"
				:min-zoom="0.3"
				:max-zoom="1.5"
				@connect="connectNodes"
				@pane-click="selectedPurpose = ''"
			>
				<Background pattern-color="#aaa" :gap="12" />
				<Panel :position="PanelPosition.TopLeft">
					<div class="column-heading">{{ __("Payment Purposes") }}</div>
				</Panel>
				<Panel :position="PanelPosition.TopRight">
					<div class="column-heading">{{ __("Reference Fields") }}</div>
				</Panel>
				<Panel :position="PanelPosition.BottomLeft">
					<button class="btn btn-sm btn-default mr-2" @click="zoomIn">+</button>
					<button class="btn btn-sm btn-default mr-2" @click="zoomOut">−</button>
					<button class="btn btn-sm btn-default" @click="fitGraph">
						{{ __("Fit") }}
					</button>
				</Panel>
				<Panel :position="PanelPosition.BottomRight">
					<div class="amount-status" :class="{ 'is-complete': hasAmountMapping }">
						<span class="indicator-dot"></span>
						{{
							hasAmountMapping
								? __("Amount is mapped")
								: __("Amount mapping is required")
						}}
					</div>
				</Panel>
				<template #node-purpose="node">
					<PurposeNode
						:node="node"
						:selected="selectedPurpose === node.data.purpose"
						@select="selectPurpose"
					/>
				</template>
				<template #node-referenceField="node">
					<FieldNode :node="node" @remove="removeField" />
				</template>
				<template #edge-mapping="edge">
					<MappingEdge v-bind="edge" @remove="removeEdge" />
				</template>
			</VueFlow>
		</section>
	</div>
</template>

<style lang="scss" scoped>
@import "@vue-flow/core/dist/style.css";
@import "@vue-flow/core/dist/theme-default.css";

.payment-mapping-visual-builder {
	display: flex;
	gap: 10px;
	height: calc(100vh - var(--navbar-height) - var(--page-head-height) - 65px);
	min-height: 600px;
}

.mapping-sidebar,
.mapping-canvas {
	border: 1px solid var(--border-color);
	border-radius: var(--radius-lg);
	background: var(--fg-color);
}

.mapping-sidebar {
	display: flex;
	flex: 0 0 305px;
	flex-direction: column;
	min-width: 0;
	padding: 16px;
	overflow: hidden;
}

.sidebar-heading h4,
.field-palette-heading h5 {
	margin: 0;
	font-weight: 600;
}

.sidebar-heading p,
.field-palette-heading p {
	margin: 5px 0 0;
	color: var(--text-muted);
	font-size: var(--text-xs);
	line-height: 1.45;
}

.doctype-control {
	margin-top: 14px;
}

.disabled-control {
	margin-top: 4px;
}

.sidebar-divider {
	margin: 14px -16px;
	border-top: 1px solid var(--border-color);
}

.field-palette-heading {
	display: flex;
	align-items: flex-start;
	justify-content: space-between;
	gap: 8px;
}

.field-search {
	position: relative;
	margin: 12px 0 8px;
}

.field-search > span {
	position: absolute;
	z-index: 1;
	top: 7px;
	left: 8px;
	color: var(--text-muted);
}

.field-search input {
	padding-left: 29px;
}

.field-palette {
	flex: 1 1 auto;
	min-height: 0;
	overflow-y: auto;
}

.field-palette-item {
	display: flex;
	align-items: center;
	gap: 7px;
	margin-bottom: 6px;
	padding: 8px;
	background: var(--subtle-fg);
	border: 1px solid transparent;
	border-radius: var(--radius-md);
	cursor: grab;
}

.field-palette-item:hover {
	border-color: var(--border-color);
	background: var(--fg-color);
}

.drag-icon {
	display: inline-flex;
	color: var(--text-muted);
}

.palette-field-name {
	flex: 1 1 auto;
	min-width: 0;
	overflow: hidden;
	font-size: var(--text-sm);
	text-overflow: ellipsis;
	white-space: nowrap;
}

.palette-empty {
	padding: 24px 8px;
	color: var(--text-muted);
	font-size: var(--text-sm);
	text-align: center;
}

.mapping-canvas {
	position: relative;
	flex: 1 1 auto;
	min-width: 0;
	overflow: hidden;
}

.loading-overlay {
	position: absolute;
	z-index: 10;
	display: flex;
	align-items: center;
	justify-content: center;
	inset: 0;
	background: color-mix(in srgb, var(--fg-color) 75%, transparent);
}

.loading-text {
	padding: 8px 12px;
	background: var(--fg-color);
	border: 1px solid var(--border-color);
	border-radius: var(--radius-md);
	box-shadow: var(--shadow-sm);
}

.column-heading,
.amount-status {
	padding: 6px 9px;
	color: var(--text-muted);
	background: var(--fg-color);
	border: 1px solid var(--border-color);
	border-radius: var(--radius-md);
	box-shadow: var(--shadow-sm);
	font-size: var(--text-xs);
	font-weight: 600;
}

.amount-status {
	display: flex;
	align-items: center;
	gap: 6px;
	color: var(--red-600);
}

.amount-status.is-complete {
	color: var(--green-600);
}

.indicator-dot {
	width: 7px;
	height: 7px;
	background: currentColor;
	border-radius: 50%;
}

:deep(.vue-flow__container) {
	cursor: default;
}

:deep(.vue-flow__edge-path.mapping-edge) {
	stroke: var(--gray-600);
	stroke-width: 1.6px;
}

:deep(.vue-flow__edge.selected .mapping-edge) {
	stroke: var(--primary);
	stroke-width: 2px;
}

:deep(.vue-flow__connection-path) {
	stroke: var(--primary);
	stroke-width: 2px;
}

@media (max-width: 900px) {
	.payment-mapping-visual-builder {
		flex-direction: column;
		height: auto;
		min-height: 0;
	}

	.mapping-sidebar {
		flex-basis: auto;
		max-height: 440px;
	}

	.mapping-canvas {
		height: 650px;
		flex-basis: 650px;
	}
}
</style>
