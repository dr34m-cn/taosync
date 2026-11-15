<script setup>
import { computed } from "vue";

const props = defineProps({
  percentage: { type: Number, default: 0 },
  precision: { type: Number, default: 3 },
  strokeWidth: { type: Number, default: 20 },
});

const percentage = computed(() => Number(
  Math.min(100, Math.max(0, props.percentage || 0)).toFixed(props.precision),
));
</script>

<template>
  <el-progress class="task-progress" :stroke-width="strokeWidth" :text-inside="true" :percentage="percentage" />
</template>

<style lang="scss" scoped>
.task-progress {
  width: 100%;
  min-width: 0;

  :deep(.el-progress-bar__innerText) {
    font-variant-numeric: tabular-nums;
  }
}

:global(html:not(.dark) .task-progress .el-progress-bar__innerText) {
  color: var(--text-primary);
  font-weight: 600;
}
</style>
