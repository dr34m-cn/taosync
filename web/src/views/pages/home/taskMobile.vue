<script setup>
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { Back, Delete, View } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { jobDeleteTask, jobGetTask } from "@/api/job";
import taskStatus from "@/utils/taskStatus";
import { parseTime } from "@/utils/utils";
import menuRefresh from "./components/menuRefresh.vue";
import taskCurrent from "./components/taskCurrent.vue";

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const firstQueryValue = (value) => (Array.isArray(value) ? value[0] : value);

const taskData = ref({
  dataList: [],
  count: 0,
});
const params = ref({
  id: firstQueryValue(route.query.jobId) ?? null,
  pageSize: 10,
  pageNum: 1,
});
const loading = ref(false);
const btnLoading = ref(false);
const currentHeight = ref(0);

const getTaskList = () => {
  if (params.value.id == null) return;
  loading.value = true;
  jobGetTask(params.value)
    .then((res) => {
      taskData.value = res.data;
    })
    .finally(() => {
      loading.value = false;
    });
};

const statusText = (row) => {
  if (row.status === 1 && row.allNum === 0) return t("task.scanning");
  if (row.status === 2 && row.allNum === 0) return t("task.noNeedSync");
  if (row.status === 6) return t("taskDetail.failedReason");
  return taskStatus(row.status);
};

const statusClass = (status) => (status < 6 ? status : 7);

const delTask = (taskId) => {
  ElMessageBox.confirm(t("task.deleteConfirm"), t("common.tips"), {
    confirmButtonText: t("common.confirm"),
    cancelButtonText: t("common.cancel"),
    type: "warning",
  }).then(() => {
    btnLoading.value = true;
    jobDeleteTask(taskId)
      .then((res) => {
        ElMessage({
          message: res.msg,
          type: "success",
        });
        getTaskList();
      })
      .finally(() => {
        btnLoading.value = false;
      });
  });
};

const detail = (taskId) => {
  router.push({
    path: "/home/task/detail",
    query: { taskId },
  });
};

const goback = () => router.go(-1);

const handleCurrentChange = (value) => {
  params.value.pageNum = value;
  getTaskList();
};

const currentChange = (value) => {
  currentHeight.value = value;
  getTaskList();
};
</script>

<template>
  <div class="mobile-task-page">
    <div class="mobile-page-header">
      <el-button :icon="Back" circle @click="goback" :aria-label="$t('common.back')" />
      <div class="header-copy">
        <h1>{{ $t("task.jobDetail") }}</h1>
        <span>{{ $t("task.mobileTaskCount", { count: taskData.count }) }}</span>
      </div>
      <menuRefresh :loading="loading" :auto-refresh="false" :need-show="1" @get-data="getTaskList" />
    </div>

    <taskCurrent
      class="mobile-current-task"
      :class="{ 'is-collapsed': currentHeight === 0 }"
      :style="{ height: currentHeight === 0 ? '0px' : 'auto' }"
      :job-id="String(params.id || '')"
      @current-change="currentChange"
    />

    <div class="history-heading">
      <h2>{{ $t("task.mobileHistory") }}</h2>
      <div class="task-legend">
        <span class="legend-dot total"></span>{{ $t("task.total") }}
        <span class="legend-dot success"></span>{{ $t("task.success") }}
        <span class="legend-dot fail"></span>{{ $t("task.fail") }}
        <span class="legend-dot other"></span>{{ $t("task.other") }}
      </div>
    </div>

    <div class="task-card-list" v-loading="loading">
      <div v-if="!loading && taskData.dataList.length === 0" class="mobile-empty">{{ $t("task.noTask") }}</div>

      <article v-for="item in taskData.dataList" :key="item.id" class="task-card">
        <div class="task-card-header">
          <div>
            <h3>{{ $t("task.mobileRecord") }} #{{ item.id }}</h3>
            <span>{{ parseTime(item.createTime) }}</span>
          </div>
          <div :class="`task-status bg-${statusClass(item.status)}`">{{ statusText(item) }}</div>
        </div>

        <div v-if="item.status == 1" class="syncing-tip">{{ $t("task.syncingProgress") }}</div>
        <div v-else class="progress-grid">
          <div class="progress-metric total">
            <span>{{ $t("task.total") }}</span>
            <strong>{{ item.allNum }}</strong>
          </div>
          <div class="progress-metric success">
            <span>{{ $t("task.success") }}</span>
            <strong>{{ item.successNum }}</strong>
          </div>
          <div class="progress-metric fail">
            <span>{{ $t("task.fail") }}</span>
            <strong>{{ item.failNum }}</strong>
          </div>
          <div class="progress-metric other">
            <span>{{ $t("task.other") }}</span>
            <strong>{{ item.otherNum }}</strong>
          </div>
        </div>

        <div v-if="item.status == 6 && item.errMsg" class="error-reason">
          <span>{{ $t("common.reason") }}</span>
          {{ item.errMsg }}
        </div>

        <div class="task-actions">
          <el-button
            type="danger"
            :icon="Delete"
            :loading="btnLoading"
            :disabled="item.status == 1"
            @click="delTask(item.id)"
          >
            {{ item.status == 1 ? $t("task.deleteUnavailable") : $t("common.delete") }}
          </el-button>
          <el-button v-if="item.allNum != 0" type="primary" :icon="View" :loading="btnLoading" @click="detail(item.id)">
            {{ $t("home.detail") }}
          </el-button>
        </div>
      </article>
    </div>

    <div v-if="taskData.count > params.pageSize" class="mobile-pagination">
      <el-pagination
        v-model:current-page="params.pageNum"
        :page-size="params.pageSize"
        :total="taskData.count"
        layout="prev, pager, next"
        @current-change="handleCurrentChange"
      />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.mobile-task-page {
  min-height: 100%;
  padding: 14px 12px 24px;
  box-sizing: border-box;
  background: var(--home-background-color);

  .mobile-page-header {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr) auto;
    align-items: center;
    gap: 10px;
    margin-bottom: 14px;

    .header-copy {
      min-width: 0;

      h1 {
        margin: 0;
        font-size: 21px;
        line-height: 1.3;
        color: var(--text-primary);
      }

      span {
        display: block;
        margin-top: 3px;
        font-size: 12px;
        color: var(--text-muted);
      }
    }
  }

  .mobile-current-task {
    width: 100%;
    min-height: 0;
    overflow: hidden;

    &.is-collapsed {
      visibility: hidden;
    }
  }

  .history-heading {
    display: flex;
    flex-direction: column;
    gap: 7px;
    margin: 4px 0 10px;

    h2 {
      margin: 0;
      font-size: 17px;
      color: var(--text-primary);
    }
  }

  .task-legend {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 4px 8px;
    font-size: 11px;
    color: var(--text-muted);

    .legend-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
    }
  }

  .total {
    --metric-color: #7048e8;
  }

  .success {
    --metric-color: var(--success-color);
  }

  .fail {
    --metric-color: var(--fail-color);
  }

  .other {
    --metric-color: var(--warning-color);
  }

  .legend-dot {
    background: var(--metric-color);
  }

  .task-card-list {
    min-height: 180px;
  }

  .mobile-empty {
    min-height: 260px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
  }

  .task-card {
    margin-bottom: 12px;
    padding: 14px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background: var(--home-item-background-color);

    .task-card-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;

      h3 {
        margin: 0;
        font-size: 16px;
        color: var(--text-primary);
      }

      span {
        display: block;
        margin-top: 4px;
        font-size: 12px;
        color: var(--text-muted);
      }
    }

    .task-status {
      flex: 0 0 auto;
      max-width: 46%;
      padding: 3px 7px;
      border-radius: 4px;
      overflow: hidden;
      font-size: 12px;
      font-weight: 700;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .syncing-tip {
      margin-top: 14px;
      padding: 16px 10px;
      border-top: 1px solid var(--border-color);
      color: var(--text-secondary);
      text-align: center;
    }

    .progress-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 6px;
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--border-color);
    }

    .progress-metric {
      min-width: 0;
      padding: 8px 4px;
      border-radius: 4px;
      text-align: center;

      span,
      strong {
        display: block;
      }

      span {
        overflow: hidden;
        font-size: 10px;
        color: var(--text-muted);
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      strong {
        margin-top: 3px;
        font-size: 17px;
        color: var(--metric-color);
      }
    }

    .progress-metric.total {
      background: rgba(112, 72, 232, 0.12);
    }

    .progress-metric.success {
      background: rgba(47, 158, 68, 0.12);
    }

    .progress-metric.fail {
      background: rgba(224, 49, 49, 0.12);
    }

    .progress-metric.other {
      background: rgba(230, 119, 0, 0.12);
    }

    .error-reason {
      margin-top: 12px;
      padding: 9px 10px;
      border-left: 3px solid var(--fail-color);
      background: rgba(224, 49, 49, 0.08);
      overflow-wrap: anywhere;
      font-size: 12px;
      line-height: 1.5;
      color: var(--text-secondary);

      span {
        margin-right: 6px;
        font-weight: 700;
        color: var(--fail-color);
      }
    }

    .task-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 12px;

      .el-button {
        width: 100%;
        margin: 0;
      }

      .el-button:only-child {
        grid-column: 1 / -1;
      }
    }
  }

  .mobile-pagination {
    display: flex;
    justify-content: center;
    padding: 8px 0 4px;
  }
}

@media (max-width: 380px) {
  .mobile-task-page {
    .task-card {
      .progress-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
  }
}
</style>
