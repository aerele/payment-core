<script setup>
import { Handle, Position } from "@vue-flow/core";

defineProps({
	node: {
		type: Object,
		required: true,
	},
});

const emit = defineEmits(["remove"]);

function isValidConnection({ source, target }) {
	return source?.startsWith("purpose-") && target?.startsWith("field-");
}
</script>

<template>
	<div class="field-node" :class="{ 'is-missing': node.data.missing }">
		<Handle
			id="field-input"
			type="target"
			:position="Position.Left"
			:is-valid-connection="isValidConnection"
		/>
		<span class="field-icon" v-html="frappe.utils.icon('data', 'sm')"></span>
		<span class="field-name">{{ node.data.label || node.data.fieldname }}</span>
		<span v-if="node.data.missing" class="missing-badge">{{ __("Missing") }}</span>
		<button
			type="button"
			class="remove-field"
			:title="__('Remove field')"
			:aria-label="__('Remove field')"
			@click.stop="emit('remove', node.id)"
		>
			×
		</button>
	</div>
</template>

<style lang="scss" scoped>
.field-node {
	position: relative;
	display: flex;
	align-items: center;
	gap: 8px;
	width: 230px;
	min-height: 48px;
	padding: 10px 12px;
	color: var(--text-color);
	background: var(--fg-color);
	border: 1px solid var(--border-color);
	border-radius: var(--radius-md);
	box-shadow: var(--shadow-sm);
}

.field-node.is-missing {
	border-color: var(--red-400);
}

.field-icon {
	display: inline-flex;
	color: var(--text-muted);
}

.field-name {
	flex: 1 1 auto;
	min-width: 0;
	overflow: hidden;
	font-size: var(--text-md);
	font-weight: 500;
	text-overflow: ellipsis;
	white-space: nowrap;
}

.missing-badge {
	padding: 2px 5px;
	color: var(--red-600);
	background: var(--red-50);
	border-radius: var(--radius-sm);
	font-size: var(--text-xs);
}

.remove-field {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	width: 22px;
	height: 22px;
	padding: 0;
	color: var(--text-muted);
	background: transparent;
	border: 0;
	border-radius: 50%;
	font-size: 18px;
	line-height: 1;
}

.remove-field:hover {
	color: var(--red-600);
	background: var(--red-50);
}

:deep(.vue-flow__handle) {
	left: -6px;
	width: 11px;
	height: 11px;
	background: var(--gray-600);
	border: 2px solid var(--fg-color);
}
</style>
