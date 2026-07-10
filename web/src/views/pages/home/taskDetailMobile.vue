<script setup>
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { Back } from "@element-plus/icons-vue";
import { jobGetTaskItem } from "@/api/job";
import taskItemStatus, { taskItemStatusKeys } from "@/utils/taskItemStatus";
import { parseSize, parseTime } from "@/utils/utils";
import menuRefresh from "./components/menuRefresh.vue";

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const firstQueryValue = (value) => (Array.isArray(value) ? value[0] : value);

const taskItemData = ref({
  dataList: [],
  count: 0,
});
const params = ref({
  taskId: firstQueryValue(route.query.taskId) ?? null,
  pageSize: 10,
  pageNum: 1,
  status: null,
  type: null,
});
const loading = ref(false);

const getTaskItemList = () => {
  if (params.value.taskId == null) return;
  loading.value = true;
  const query = { ...params.value };
  if (query.status === null || query.status === "") delete query.status;
  if (query.type === null || query.type === "") delete query.type;
  jobGetTaskItem(query)
    .then((res) => {
      res.data.dataList.forEach((item) => {
        item.progress = Math.min(parseInt(item.progress || 0), 100);
      });
      taskItemData.value = res.data;
    })
    .finally(() => {
      loading.value = false;
    });
};

const typeText = (row) => {
  if (row.type === 0) return row.isPath ? t("taskDetail.create") : t("taskDetail.copy");
  if (row.type === 1) return t("taskDetail.delete");
  return t("taskDetail.move");
};

const statusText = (row) => (row.status === 7 ? t("taskDetail.failedReason") : taskItemStatus(row.status));

const goback = () => router.go(-1);

const filterChange = () => {
  params.value.pageNum = 1;
  getTaskItemList();
};

const handleCurrentChange = (value) => {
  params.value.pageNum = value;
  getTaskItemList();
};
</script>

<template>
  <div class="mobile-task-detail-page">
    <div class="mobile-page-header">
      <el-button :icon="Back" circle @click="goback" :aria-label="$t('common.back')" />
      <div class="header-copy">
        <h1>{{ $t("taskDetail.title") }}</h1>
        <span>{{ $t("taskDetail.mobileItemCount", { count: taskItemData.count }) }}</span>
      </div>
      <menuRefresh :fresh-interval="9973" :auto-refresh="false" :loading="loading" :need-show="1" @get-data="getTaskItemList" />
    </div>

    <div class="mobile-filters">
      <el-select v-model="params.status" :placeholder="$t('taskDetail.filterStatus')" clearable @change="filterChange">
        <el-option v-for="(item, index) in taskItemStatusKeys" :key="item" :label="$t(item)" :value="index" />
      </el-select>
      <el-select v-model="params.type" :placeholder="$t('taskDetail.filterType')" clearable @change="filterChange">
        <el-option :label="$t('taskDetail.copyCreate')" :value="0" />
        <el-option :label="$t('taskDetail.delete')" :value="1" />
        <el-option :label="$t('taskDetail.move')" :value="2" />
      </el-select>
    </div>

    <div class="task-item-list" v-loading="loading">
      <div v-if="!loading && taskItemData.dataList.length === 0" class="mobile-empty">{{ $t("taskDetail.mobileNoItems") }}</div>

      <article v-for="item in taskItemData.dataList" :key="item.id" class="task-item-card">
        <div class="task-item-header">
          <h2>{{ item.fileName || item.dstPath }}</h2>
          <div :class="`operation-type type-${item.type}`">{{ typeText(item) }}</div>
        </div>

        <div class="status-line">
          <el-progress
            v-if="item.status == 1"
            :stroke-width="18"
            :text-inside="true"
            :percentage="Number(Number(item.progress || 0).toFixed(3))"
          />
          <div v-else :class="`item-status bg-${item.status}`">{{ statusText(item) }}</div>
        </div>

        <div class="item-meta">
          <div>
            <span>{{ $t("taskDetail.fileSize") }}</span>
            <strong>{{ parseSize(item.fileSize) }}</strong>
          </div>
          <div>
            <span>{{ $t("common.createdAt") }}</span>
            <strong>{{ parseTime(item.createTime) }}</strong>
          </div>
        </div>

        <div v-if="item.type != 1" class="path-block">
          <span>{{ $t("taskDetail.sourcePath") }}</span>
          <div class="path-value source-path">{{ item.srcPath }}</div>
        </div>
        <div class="path-block">
          <span>{{ $t("taskDetail.targetPath") }}</span>
          <div class="path-value target-path">{{ item.dstPath }}</div>
        </div>

        <div v-if="item.status == 7 && item.errMsg" class="error-reason">
          <span>{{ $t("common.reason") }}</span>
          {{ item.errMsg }}
        </div>
      </article>
    </div>

    <div v-if="taskItemData.count > params.pageSize" class="mobile-pagination">
      <el-pagination
        v-model:current-page="params.pageNum"
        :page-size="params.pageSize"
        :total="taskItemData.count"
        layout="prev, pager, next"
        @current-change="handleCurrentChange"
      />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.mobile-task-detail-page {
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

  .mobile-filters {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin-bottom: 12px;

    .el-select {
      width: 100%;
    }
  }

  .task-item-list {
    min-height: 200px;
  }

  .mobile-empty {
    min-height: 280px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-muted);
    text-align: center;
  }

  .task-item-card {
    margin-bottom: 12px;
    padding: 14px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background: var(--home-item-background-color);

    .task-item-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;

      h2 {
        min-width: 0;
        margin: 0;
        overflow-wrap: anywhere;
        font-size: 16px;
        line-height: 1.4;
        color: var(--text-primary);
      }
    }

    .operation-type {
      flex: 0 0 auto;
      padding: 3px 7px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 700;
    }

    .type-0 {
      color: #7048e8;
      background: rgba(112, 72, 232, 0.12);
    }

    .type-1,
    .type-2 {
      color: var(--warning-color);
      background: rgba(230, 119, 0, 0.12);
    }

    .status-line {
      margin: 13px 0;
      padding: 12px 0;
      border-top: 1px solid var(--border-color);
      border-bottom: 1px solid var(--border-color);
    }

    .item-status {
      width: fit-content;
      min-width: 76px;
      padding: 3px 8px;
      border-radius: 4px;
      box-sizing: border-box;
      font-size: 12px;
      font-weight: 700;
      text-align: center;
    }

    .item-meta {
      display: grid;
      grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr);
      gap: 12px;
      margin-bottom: 13px;

      span,
      strong {
        display: block;
      }

      span {
        font-size: 11px;
        color: var(--text-muted);
      }

      strong {
        margin-top: 3px;
        overflow-wrap: anywhere;
        font-size: 13px;
        color: var(--text-primary);
      }
    }

    .path-block + .path-block {
      margin-top: 10px;
    }

    .path-block > span {
      display: block;
      margin-bottom: 5px;
      font-size: 11px;
      color: var(--text-muted);
    }

    .path-value {
      padding: 7px 8px;
      border-radius: 4px;
      overflow-wrap: anywhere;
      font-size: 12px;
      line-height: 1.45;
    }

    .source-path {
      color: #7048e8;
      background: rgba(112, 72, 232, 0.1);
    }

    .target-path {
      color: var(--active-color);
      background: rgba(37, 99, 235, 0.1);
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
  }

  .mobile-pagination {
    display: flex;
    justify-content: center;
    padding: 8px 0 4px;
  }
}

@media (max-width: 380px) {
  .mobile-task-detail-page {
    .mobile-filters,
    .task-item-card .item-meta {
      grid-template-columns: minmax(0, 1fr);
    }
  }
}
</style>
