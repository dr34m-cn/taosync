<script setup>
import { computed } from "vue";
import { formatDuration, parseTime, parseSize } from "@/utils/utils";
import RetryAllButton from "./RetryAllButton.vue";

const props = defineProps({ task: { type: Object, required: true } });
defineEmits(["submitted"]);
const operations = [
  ["copy", "taskDetail.copy"], ["move", "taskDetail.move"], ["delete", "taskDetail.delete"],
];
const totals = computed(() => operations.reduce((sum, [key]) => {
  const group = props.task.fileStats[key];
  return { count: sum.count + (group?.count ?? 0), size: sum.size + (group?.size ?? 0) };
}, { count: 0, size: 0 }));
</script>

<template>
  <details class="history-stats">
    <summary>{{ $t("taskDetail.processedFiles", totals.count) }} · {{ parseSize(totals.size) }}</summary>
    <dl>
      <dt>{{ $t("current.startAt") }}</dt><dd>{{ parseTime(task.runTime || task.createTime) || $t("taskDetail.unrecorded") }}</dd>
      <dt>{{ $t("taskDetail.endTime") }}</dt><dd>{{ parseTime(task.endTime) || $t("taskDetail.unrecorded") }}</dd>
      <dt>{{ $t("home.duration") }}</dt><dd>{{ task.duration == null ? $t("taskDetail.unrecorded") : formatDuration(task.duration, $t) }}</dd>
      <template v-for="[key, label] in operations" :key="key">
        <dt>{{ $t(label) }}</dt>
        <dd>{{ $t("taskDetail.filesCount", task.fileStats[key]?.count ?? 0) }} · {{ parseSize(task.fileStats[key]?.size ?? 0) }}</dd>
      </template>
      <template v-if="task.fileStats.rapidUpload?.count">
        <dt>{{ $t("taskDetail.instantUpload") }}</dt>
        <dd>{{ $t("taskDetail.filesCount", task.fileStats.rapidUpload.count) }} · {{ parseSize(task.fileStats.rapidUpload.size ?? 0) }}</dd>
      </template>
      <template v-if="task.fileStats.failed">
        <dt>{{ $t("task.fail") }}</dt>
        <dd>{{ $t("taskDetail.filesCount", task.fileStats.failed.count) }} · {{ parseSize(task.fileStats.failed.size) }}</dd>
      </template>
    </dl>
    <RetryAllButton v-if="task.status > 1 && task.failNum > 0" class="retry-all" :task-id="task.id" @submitted="$emit('submitted')" />
  </details>
</template>

<style scoped>
.history-stats { font-size: 13px; font-variant-numeric: tabular-nums; }
summary { cursor: pointer; color: var(--text-primary); }
dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 8px 0 0; }
dt { color: var(--text-muted); }
dd { margin: 0; overflow-wrap: anywhere; }
.retry-all { margin-top: 8px; }
</style>
