<script setup>
import { computed } from "vue";
import { formatDuration, parseTime, parseSize } from "@/utils/utils";

const props = defineProps({ task: { type: Object, required: true } });
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
    <summary>成功处理 {{ totals.count }} 个文件 · {{ parseSize(totals.size) }}</summary>
    <dl>
      <dt>{{ $t("current.startAt") }}</dt><dd>{{ parseTime(task.runTime || task.createTime) || "未记录" }}</dd>
      <dt>结束时间</dt><dd>{{ parseTime(task.endTime) || "未记录" }}</dd>
      <dt>{{ $t("home.duration") }}</dt><dd>{{ task.duration == null ? "未记录" : formatDuration(task.duration, $t) }}</dd>
      <template v-for="[key, label] in operations" :key="key">
        <dt>{{ $t(label) }}</dt>
        <dd>{{ task.fileStats[key]?.count ?? 0 }} 个文件 · {{ parseSize(task.fileStats[key]?.size ?? 0) }}</dd>
      </template>
      <template v-if="task.fileStats.failed">
        <dt>{{ $t("task.fail") }}</dt>
        <dd>{{ task.fileStats.failed.count }} 个文件 · {{ parseSize(task.fileStats.failed.size) }}</dd>
      </template>
    </dl>
  </details>
</template>

<style scoped>
.history-stats { font-size: 13px; font-variant-numeric: tabular-nums; }
summary { cursor: pointer; color: var(--text-primary); }
dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 8px 0 0; }
dt { color: var(--text-muted); }
dd { margin: 0; overflow-wrap: anywhere; }
</style>
