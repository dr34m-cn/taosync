<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { jobGetTaskCurrent, jobPut } from "@/api/job";
import taskCurrentEcharts from "./taskCurrentEcharts.vue";
import taskDetailTable from "./taskDetailTable.vue";
import taskProgress from "./taskProgress.vue";
import { parseSize, parseTime } from "@/utils/utils";
import { ElMessage, ElMessageBox } from "element-plus";
import { useI18n } from "vue-i18n";
import { useMediaQuery } from "@vueuse/core";

const props = defineProps({
  jobId: {
    type: String,
    default: null,
  },
});
const emit = defineEmits(["currentChange"]);
const { t } = useI18n();
const isMobile = useMediaQuery("(max-width: 768px)");
const currentPanelHeight = computed(() => (isMobile.value ? 1240 : 479));

const loading = ref(false);
const loadingTask = ref(false);
const cuTaskSelect = ref(1);
const cuTaskList = ref([]);
const toTableParams = ref({
  pageSize: 10,
  pageNum: 1,
});
const current = ref(null);
let timer = null;

const summaryMetrics = computed(() => {
  const counts = current.value?.num || {};
  const sizes = current.value?.size || {};
  const statuses = ["wait", "running", "success", "fail", "other"];
  return [
    {
      key: "total",
      label: "current.totalFiles",
      count: statuses.reduce((sum, key) => sum + (counts[key] || 0), 0),
      size: statuses.reduce((sum, key) => sum + (sizes[key] || 0), 0),
    },
    ...[
      ["success", "current.completed"],
      ["running", "current.running"],
      ["wait", "current.wait"],
    ].map(([key, label]) => ({ key, label, count: counts[key] || 0, size: sizes[key] || 0 })),
  ];
});

const toTable = computed(() => {
  const count = cuTaskList.value.length;
  let dataList = [];
  if (count !== 0) {
    const startIndex = (toTableParams.value.pageNum - 1) * toTableParams.value.pageSize;
    dataList = cuTaskList.value.slice(startIndex, startIndex + toTableParams.value.pageSize);
  }
  return {
    dataList,
    count,
  };
});

const formatSeconds = (seconds) => {
  seconds = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const days = Math.floor(seconds / (24 * 3600));
  const hours = Math.floor((seconds % (24 * 3600)) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const timeUnits = [
    { value: days, unit: t("time.day") },
    { value: hours, unit: t("time.hour") },
    { value: minutes, unit: t("time.minute") },
    { value: secs, unit: t("time.second") },
  ];
  const nonZeroUnits = timeUnits.filter((unit) => unit.value > 0);
  if (nonZeroUnits.length === 0) return `0${t("time.second")}`;
  return nonZeroUnits.map((unit) => `${unit.value}${unit.unit}`).join(" ");
};

const calcSpeedAndSize = (nextCurrent) => {
  const doingSize = nextCurrent.doingTask.reduce((sum, obj) => {
    return sum + (obj.fileSize || 0) * ((obj.progress || 0) / 100.0);
  }, 0);
  const remainSize = nextCurrent.size.running - doingSize + nextCurrent.size.wait;
  const doneSize = nextCurrent.size.success + doingSize;
  let speed = 0;
  if (current.value !== null) {
    speed = current.value.speed;
    if (nextCurrent.duration - current.value.duration !== 0 && doneSize - current.value.doneSize !== 0) {
      speed = (doneSize - current.value.doneSize) / (nextCurrent.duration - current.value.duration);
    }
  }
  const syncDuration = nextCurrent.duration - nextCurrent.firstSync + nextCurrent.createTime;
  const speedAvg = syncDuration > 0 ? doneSize / syncDuration : 0;
  const remainTime = speedAvg > 0 ? parseInt(remainSize / speedAvg) : 0;
  const displayRemainTime = remainTime > 24 * 3600 ? Math.ceil(remainTime / 60) * 60 : remainTime;
  const allSize = doneSize + remainSize;
  return {
    remainSize,
    doneSize,
    speedAvg,
    speed,
    remainTime,
    remainTimeText: formatSeconds(displayRemainTime),
    allProgress: allSize > 0 ? (doneSize / allSize) * 100 : 0,
  };
};

const show = () => {
  emit("currentChange", currentPanelHeight.value);
};

const hide = () => {
  emit("currentChange", 0);
};

const getTaskList = () => {
  if (current.value === null || loadingTask.value || cuTaskSelect.value === 1) {
    return;
  }
  loadingTask.value = true;
  const status = cuTaskSelect.value;
  jobGetTaskCurrent({
    id: props.jobId,
    status,
  })
    .then((res) => {
      if (cuTaskSelect.value === status) {
        cuTaskList.value = res.data || [];
      }
    })
    .catch(() => {})
    .finally(() => {
      loadingTask.value = false;
      if (cuTaskSelect.value !== status) getTaskList();
    });
};

const dealWithCurrent = (nextCurrent) => {
  if (nextCurrent === null) {
    if (current.value !== null) {
      hide();
    }
    current.value = null;
    setTimeout(() => {
      loading.value = false;
    }, 9973);
  } else {
    if (current.value === null) {
      show();
    }
    nextCurrent.durationText = formatSeconds(nextCurrent.duration);
    const calcs = calcSpeedAndSize(nextCurrent);
    if (cuTaskSelect.value === 1) {
      cuTaskList.value = nextCurrent.doingTask;
    }
    current.value = {
      ...nextCurrent,
      ...calcs,
    };
    loading.value = false;
    getTaskList();
  }
};

const getCurrent = () => {
  if (loading.value || !props.jobId) {
    return;
  }
  loading.value = true;
  jobGetTaskCurrent({
    id: props.jobId,
  })
    .then((res) => {
      dealWithCurrent(res.data);
    })
    .catch(() => {
      setTimeout(() => {
        loading.value = false;
      }, 9973);
    });
};

const startRefresh = () => {
  timer = setInterval(() => {
    getCurrent();
  }, 610);
  getCurrent();
};

const endRefresh = () => {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
};

const changeTaskCu = (status) => {
  if (cuTaskSelect.value === status) {
    return;
  }
  cuTaskSelect.value = status;
  toTableParams.value.pageNum = 1;
  if (status === 1) {
    cuTaskList.value = current.value?.doingTask || [];
  } else {
    cuTaskList.value = [];
    getTaskList();
  }
};

const pageChange = (val) => {
  toTableParams.value = val;
};

const abortJob = () => {
  ElMessageBox.confirm(t("current.abortConfirm"), t("common.tips"), {
    confirmButtonText: t("common.confirm"),
    cancelButtonText: t("common.cancel"),
    type: "warning",
  }).then(() => {
    jobPut({
      pause: true,
      id: Number(props.jobId),
      abort: true,
    }).then(() => {
      ElMessage({
        message: t("current.abortSent"),
        type: "success",
      });
    });
  });
};

onMounted(() => {
  startRefresh();
});

onBeforeUnmount(() => {
  endRefresh();
});

watch(isMobile, () => {
  if (current.value !== null) {
    show();
  }
});
</script>

<template>
  <div class="task-current">
    <div class="content-none-data" v-if="current === null">
      {{ loading ? $t("loading") : $t("current.notRunning") }}
    </div>
    <div class="current-box" v-else>
      <div class="current-box-top">
        <div class="current-box-top-left">
          <div class="top-line">
            <div class="metric">
              {{ $t("current.overall") }}:
              <span v-if="current.firstSync === null">{{ $t("current.noSyncFound") }}</span>
              <template v-else>
                <taskProgress
                  style="width: 130px"
                  :percentage="current.allProgress"
                  :precision="4"
                />
                <el-tooltip v-if="!current.scanFinish" effect="dark" :content="$t('current.unreliableProgress')" placement="top-end">
                  <el-icon class="hint"><QuestionFilled /></el-icon>
                </el-tooltip>
              </template>
            </div>
            <div class="metric">
              {{ $t("current.currentStatus") }}:
              {{
                current.scanFinish
                  ? $t("current.scanDoneSyncing")
                  : current.firstSync === null
                    ? $t("current.scanningOnly")
                    : $t("current.scanningSyncing")
              }}
            </div>
            <div class="metric">
              {{ $t("current.avgSpeed") }}:
              <span v-if="current.firstSync === null">--</span>
              <span v-else>
                {{ parseSize(current.speedAvg) }}/s
                <el-tooltip effect="dark" placement="top-end" :content="$t('current.speedTip')">
                  <el-icon class="hint"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </div>
            <div class="metric">
              {{ $t("current.instantSpeed") }}:
              <span v-if="current.firstSync === null">--</span>
              <span v-else>{{ parseSize(current.speed) }}/s</span>
            </div>
          </div>
          <div class="top-line">
            <div class="metric">{{ $t("current.duration") }}: {{ current.durationText }}</div>
            <div class="metric">
              {{ $t("current.remaining") }}:
              {{ current.firstSync === null ? "--" : current.remainTimeText }}
              <el-tooltip effect="dark" placement="top-end" :content="$t('current.timeTip')">
                <el-icon class="hint"><QuestionFilled /></el-icon>
              </el-tooltip>
            </div>
            <div class="metric">{{ $t("current.startAt") }}: {{ parseTime(current.createTime) }}</div>
            <div class="metric">
              {{ $t("current.finishAt") }}:
              <span v-if="current.firstSync === null">--</span>
              <span v-else>
                {{ parseTime(current.createTime + current.duration + current.remainTime) }}
                <el-tooltip effect="dark" placement="top-end" :content="$t('current.timeTip')">
                  <el-icon class="hint"><QuestionFilled /></el-icon>
                </el-tooltip>
              </span>
            </div>
          </div>
          <div class="top-line summary-line">
            <div v-for="metric in summaryMetrics" :key="metric.key" class="metric">
              <span>{{ $t(metric.label) }}:</span>
              <span class="metric-value">{{ metric.count }} ({{ parseSize(metric.size) }})</span>
            </div>
          </div>
        </div>
        <div class="current-box-top-right">
          <el-button type="danger" @click="abortJob">{{ $t("current.abort") }}</el-button>
        </div>
      </div>
      <div class="current-box-bottom">
        <div class="content-none-data" v-if="current.firstSync === null">{{ $t("current.noFilesYet") }}</div>
        <taskCurrentEcharts v-else class="current-echart-box" :taskCurrent="current" />
        <div class="current-box-task">
          <div class="current-box-task-left">
            <div @click="changeTaskCu(0)" :class="`task-left-item${cuTaskSelect == 0 ? ' is-current' : ''}`">
              {{ $t("current.wait") }}
            </div>
            <div @click="changeTaskCu(1)" :class="`task-left-item${cuTaskSelect == 1 ? ' is-current' : ''}`">
              {{ $t("current.running") }}
            </div>
            <div @click="changeTaskCu(2)" :class="`task-left-item${cuTaskSelect == 2 ? ' is-current' : ''}`">
              {{ $t("current.success") }}
            </div>
            <div @click="changeTaskCu(7)" :class="`task-left-item${cuTaskSelect == 7 ? ' is-current' : ''}`">
              {{ $t("current.fail") }}
            </div>
            <div @click="changeTaskCu(-1)" :class="`task-left-item${cuTaskSelect == -1 ? ' is-current' : ''}`">
              {{ $t("current.other") }}
            </div>
          </div>
          <taskDetailTable :key="cuTaskSelect" class="current-box-task-right" :taskItemData="toTable" @pageChange="pageChange" />
        </div>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.task-current {
  .current-box {
    background-color: var(--home-item-background-color);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    height: calc(100% - 12px);
    padding: 2px 10px;
    width: 100%;
    box-sizing: border-box;
    overflow-x: auto;
    display: flex;
    flex-direction: column;

    .current-box-top {
      min-width: 1120px;
      box-sizing: border-box;
      min-height: 64px;
      padding: 6px 0;
      border-bottom: 1px dotted var(--border-color);
      display: flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;

      .top-line {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 28px;

        .metric {
          width: 270px;
          display: flex;
          align-items: center;
          color: var(--text-secondary);
        }
      }

      .summary-line .metric {
        gap: 4px;
        flex-wrap: wrap;
        padding: 3px 0;
        line-height: 22px;

        .metric-value {
          min-width: 0;
          overflow-wrap: anywhere;
          color: var(--text-primary);
          font-variant-numeric: tabular-nums;
        }
      }

      .current-box-top-right {
        margin-left: 16px;
      }
    }

    .current-box-bottom {
      min-width: 1120px;
      box-sizing: border-box;
      min-height: 0;
      flex: 1;
      width: 100%;
      display: flex;

      .current-echart-box,
      .content-none-data {
        height: 100%;
        width: 40%;
        min-width: 390px;
        box-sizing: border-box;
        border-right: 1px dotted var(--border-color);
      }

      .current-box-task {
        width: 60%;
        height: 100%;
        box-sizing: border-box;
        padding: 8px 0 8px 12px;
        display: flex;

        .current-box-task-left {
          width: 72px;
          height: 100%;

          .task-left-item {
            cursor: pointer;
            width: 72px;
            margin: 14px 0;
            padding: 3px 8px 3px 0;
            color: var(--text-muted);
            text-align: right;
            box-sizing: border-box;
          }

          .is-current {
            color: var(--active-color);
            border-right: 3px solid var(--active-color);
            background-color: rgba(37, 99, 235, 0.12);
          }
        }

        .current-box-task-right {
          margin-left: 8px;
          width: calc(100% - 80px);
          height: 100%;
        }
      }
    }
  }

  .hint {
    margin-left: 6px;
    color: var(--text-muted);
  }
}

@media (max-width: 768px) {
  .task-current {
    .current-box {
      height: auto;
      padding: 6px 10px;
      overflow-x: hidden;
      overflow-y: visible;

      .current-box-top {
        min-width: 0;
        min-height: 0;
        padding: 8px 0 12px;
        flex-direction: column;
        align-items: stretch;

        .current-box-top-left {
          width: 100%;
        }

        .top-line {
          display: grid;
          grid-template-columns: minmax(0, 1fr);
          justify-content: stretch;

          .metric {
            width: auto;
            min-width: 0;
            min-height: 30px;
            align-items: flex-start;
            flex-wrap: wrap;
            overflow-wrap: anywhere;
          }
        }

        .current-box-top-right {
          margin: 8px 0 0;

          .el-button {
            width: 100%;
          }
        }
      }

      .current-box-bottom {
        min-width: 0;
        height: auto;
        display: flex;
        flex-direction: column;

        .current-echart-box,
        .content-none-data {
          width: 100%;
          min-width: 0;
          height: 300px;
          flex: 0 0 300px;
          border-right: 0;
          border-bottom: 1px dotted var(--border-color);
        }

        .current-box-task {
          width: 100%;
          height: 500px;
          flex: 0 0 500px;
          padding: 8px 0 0;
          flex-direction: column;

          .current-box-task-left {
            width: 100%;
            height: 44px;
            display: flex;
            overflow-x: auto;
            overflow-y: hidden;

            .task-left-item {
              width: auto;
              min-width: 64px;
              margin: 0;
              padding: 10px 12px 8px;
              flex: 0 0 auto;
              text-align: center;
              border-right: 0;
              border-bottom: 3px solid transparent;
            }

            .is-current {
              border-right: 0;
              border-bottom-color: var(--active-color);
            }
          }

          .current-box-task-right {
            width: 100%;
            height: 448px;
            margin: 8px 0 0;
          }
        }
      }
    }
  }
}
</style>
