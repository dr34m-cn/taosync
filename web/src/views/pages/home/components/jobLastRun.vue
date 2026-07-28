<script setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import taskStatus from "@/utils/taskStatus";
import { parseTime } from "@/utils/utils";

const props = defineProps({
  task: {
    type: Object,
    default: null,
  },
});

const { t } = useI18n();

const total = computed(() => Math.max(0, Number(props.task?.allNum) || 0));
const success = computed(() => Math.max(0, Number(props.task?.successNum) || 0));
const failed = computed(() => Math.max(0, Number(props.task?.failNum) || 0));
const status = computed(() => Number(props.task?.status));
const noNeedSync = computed(() => Boolean(props.task) && status.value === 2 && total.value === 0);

const statusText = computed(() => {
  if (!props.task) return t("home.noLastRun");
  if (noNeedSync.value) return t("task.noNeedSync");
  return taskStatus(status.value);
});

const statusClass = computed(() => {
  if (status.value >= 7) return 7;
  if (status.value >= 0 && status.value <= 6) return status.value;
  return 0;
});

const executionTime = computed(() => parseTime(props.task?.runTime || props.task?.createTime) || "--");

const durationText = computed(() => {
  if (props.task?.duration === null || props.task?.duration === undefined) return "--";
  const seconds = Math.max(0, Number(props.task.duration) || 0);
  const units = [
    { value: Math.floor(seconds / 86400), unit: t("time.day") },
    { value: Math.floor((seconds % 86400) / 3600), unit: t("time.hour") },
    { value: Math.floor((seconds % 3600) / 60), unit: t("time.minute") },
    { value: Math.floor(seconds % 60), unit: t("time.second") },
  ].filter((item) => item.value > 0);
  return units.length ? units.map((item) => `${item.value}${item.unit}`).join(" ") : `0${t("time.second")}`;
});

const successRate = computed(() => {
  if (total.value === 0) return "--";
  return `${success.value}/${total.value} (${Math.round((success.value / total.value) * 100)}%)`;
});
</script>

<template>
  <div class="job-last-run" :class="{ 'is-empty': !task }">
    <div v-if="task" class="job-last-run-status">
      <span :class="`bg-status bg-${statusClass}`">{{ statusText }}</span>
    </div>
    <span v-else class="job-last-run-empty">{{ statusText }}</span>
    <div v-if="task" class="job-last-run-metrics">
      <div>
        <span>{{ $t("home.executionTime") }}</span>
        <strong>{{ executionTime }}</strong>
      </div>
      <div>
        <span>{{ $t("home.duration") }}</span>
        <strong>{{ durationText }}</strong>
      </div>
      <div>
        <span>{{ $t("home.successRate") }}</span>
        <strong>{{ successRate }}</strong>
      </div>
      <div v-if="failed > 0">
        <span>{{ $t("task.fail") }}</span>
        <strong class="job-last-run-failed">{{ failed }}</strong>
      </div>
    </div>
  </div>
</template>

<style scoped>
.job-last-run {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
}

.job-last-run-status {
  display: flex;
  align-items: center;
}

.job-last-run-status .bg-status {
  font-size: 12px;
}

.job-last-run-empty {
  color: var(--text-muted);
}

.job-last-run-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px 16px;
}

.job-last-run-metrics > div {
  min-width: 0;
}

.job-last-run-metrics span,
.job-last-run-metrics strong {
  display: block;
}

.job-last-run-metrics span {
  color: var(--text-muted);
  font-size: 12px;
}

.job-last-run-metrics strong {
  margin-top: 3px;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.job-last-run-failed {
  color: var(--fail-color) !important;
}

@media (max-width: 860px) {
  .job-last-run-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
