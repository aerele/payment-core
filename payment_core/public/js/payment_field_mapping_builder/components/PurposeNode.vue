<script setup>
import { Handle, Position } from "@vue-flow/core";

defineProps({
	node: {
		type: Object,
		required: true,
	},
	selected: {
		type: Boolean,
		default: false,
	},
});

const emit = defineEmits(["select"]);

function isValidConnection({ source, target }) {
	return source?.startsWith("purpose-") && target?.startsWith("field-");
}
</script>

<template>
	<button
		type="button"
		class="purpose-node"
		:class="{ 'is-required': node.data.required, 'is-selected': selected }"
		@click.stop="emit('select', node.data.purpose)"
	>
		<span class="purpose-dot"></span>
		<span class="purpose-copy">
			<span class="purpose-label">{{ __(node.data.label) }}</span>
			<span class="purpose-key">
				{{ node.data.purpose }}
				<template v-if="node.data.required"> · {{ __("required") }}</template>
			</span>
		</span>
		<Handle
			id="purpose-output"
			type="source"
			:position="Position.Right"
			:is-valid-connection="isValidConnection"
		/>
	</button>
</template>

<style lang="scss" scoped>
.purpose-node {
	position: relative;
	display: flex;
	align-items: center;
	gap: 10px;
	width: 215px;
	min-height: 58px;
	padding: 10px 20px 10px 14px;
	text-align: left;
	color: var(--text-color);
	background: var(--fg-color);
	border: 1px solid var(--border-color);
	border-radius: var(--radius-md);
	box-shadow: var(--shadow-sm);
	transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.purpose-node:hover,
.purpose-node.is-selected {
	border-color: var(--primary);
	box-shadow: 0 0 0 2px var(--blue-100);
}

.purpose-node.is-required {
	border-left: 3px solid var(--orange-500);
}

.purpose-dot {
	flex: 0 0 auto;
	width: 8px;
	height: 8px;
	border-radius: 50%;
	background: var(--gray-400);
}

.is-required .purpose-dot {
	background: var(--orange-500);
}

.purpose-copy {
	display: flex;
	flex-direction: column;
	min-width: 0;
}

.purpose-label {
	font-size: var(--text-md);
	font-weight: 600;
	line-height: 1.3;
}

.purpose-key {
	margin-top: 3px;
	color: var(--text-muted);
	font-size: var(--text-xs);
	font-weight: 400;
}

:deep(.vue-flow__handle) {
	right: -6px;
	width: 11px;
	height: 11px;
	background: var(--gray-600);
	border: 2px solid var(--fg-color);
}
</style>
