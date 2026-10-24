<script setup>
import { EdgeLabelRenderer, SmoothStepEdge, getSmoothStepPath } from "@vue-flow/core";
import { computed } from "vue";

const props = defineProps({
	id: {
		type: String,
		required: true,
	},
	sourceX: {
		type: Number,
		required: true,
	},
	sourceY: {
		type: Number,
		required: true,
	},
	targetX: {
		type: Number,
		required: true,
	},
	targetY: {
		type: Number,
		required: true,
	},
	sourcePosition: {
		type: String,
		default: undefined,
	},
	targetPosition: {
		type: String,
		default: undefined,
	},
	markerEnd: {
		type: String,
		default: undefined,
	},
});

const emit = defineEmits(["remove"]);

const path = computed(() =>
	getSmoothStepPath({
		sourceX: props.sourceX,
		sourceY: props.sourceY,
		targetX: props.targetX,
		targetY: props.targetY,
		sourcePosition: props.sourcePosition,
		targetPosition: props.targetPosition,
		borderRadius: 18,
	})
);
</script>

<script>
export default {
	inheritAttrs: false,
};
</script>

<template>
	<SmoothStepEdge class="mapping-edge" :id="id" :path="path[0]" :marker-end="markerEnd" />
	<EdgeLabelRenderer>
		<button
			type="button"
			class="edge-remove nodrag nopan"
			:style="{
				transform: 'translate(-50%, -50%) translate(' + path[1] + 'px, ' + path[2] + 'px)',
			}"
			:title="__('Remove mapping')"
			:aria-label="__('Remove mapping')"
			@click.stop="emit('remove', id)"
		>
			×
		</button>
	</EdgeLabelRenderer>
</template>

<style lang="scss" scoped>
.edge-remove {
	position: absolute;
	display: flex;
	align-items: center;
	justify-content: center;
	width: 22px;
	height: 22px;
	padding: 0;
	pointer-events: all;
	color: var(--gray-600);
	background: var(--fg-color);
	border: 1px solid var(--gray-400);
	border-radius: 50%;
	box-shadow: var(--shadow-sm);
	font-size: 16px;
	line-height: 1;
}

.edge-remove:hover {
	color: var(--red-600);
	border-color: var(--red-400);
}
</style>
