<script setup>
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import taskStatus from "@/utils/taskStatus";
import { formatDuration, parseSize, parseTime } from "@/utils/utils";

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

const durationText = computed(() => props.task?.duration == null ? "--" : formatDuration(props.task.duration, t));

const successRate = computed(() => {
  if (total.value === 0) return "--";
  return `${success.value}/${total.value} (${Math.round((success.value / total.value) * 100)}%)`;
});
</script>

<template>
  <div class="job-last-run" :class="{ 'is-empty': !task }">
    <span v-if="!task" class="job-last-run-empty">{{ statusText }}</span>
    <div v-else class="job-last-run-metrics">
      <div class="job-last-run-start">
        <div :class="`bg-status bg-${statusClass}`">{{ statusText }}</div>
        <div>
          <span>{{ $t("home.executionTime") }}</span>
          <strong>{{ executionTime }}</strong>
        </div>
      </div>
      <div>
        <span>{{ $t("home.duration") }}</span>
        <strong>{{ durationText }}</strong>
      </div>
      <div>
        <span>{{ $t("home.successRate") }}</span>
        <strong>{{ successRate }}</strong>
      </div>
      <div>
        <span>{{ $t("task.success") }}</span>
        <strong>{{ $t("taskDetail.mobileItemCount", { count: task.successFileNum }) }} · {{ parseSize(task.successFileSize) }}</strong>
      </div>
      <div v-if="failed > 0">
        <span>{{ $t("task.fail") }}</span>
        <strong class="job-last-run-failed">{{ failed }} · {{ parseSize(task.failFileSize) }}</strong>
      </div>
    </div>
  </div>
</template>

<style scoped>
.job-last-run {
  min-width: 0;
}

.job-last-run-start {
  display: flex;
  align-items: center;
  gap: 12px;
}

.job-last-run-start .bg-status {
  flex: none;
  font-size: 12px;
}

.job-last-run-empty {
  color: var(--text-muted);
}

.job-last-run-metrics {
  display: flex;
  flex-wrap: wrap;
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
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
  overflow-wrap: anywhere;
  white-space: normal;
}

.job-last-run-failed {
  color: var(--fail-color) !important;
}

@media (max-width: 860px) {
  .job-last-run-metrics {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .job-last-run-start {
    grid-column: 1 / -1;
  }
}
</style>
