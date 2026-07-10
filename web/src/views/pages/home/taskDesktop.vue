<script setup>
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { jobDeleteTask, jobGetTask } from "@/api/job";
import menuRefresh from "./components/menuRefresh.vue";
import taskCurrent from "./components/taskCurrent.vue";
import taskStatus from "@/utils/taskStatus";
import { parseTime } from "@/utils/utils";
import { Back, Delete, View } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useI18n } from "vue-i18n";
import { useMediaQuery } from "@vueuse/core";

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const isMobile = useMediaQuery("(max-width: 768px)");
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
    query: {
      taskId,
    },
  });
};

const goback = () => {
  router.go(-1);
};

const handleSizeChange = (val) => {
  params.value.pageSize = val;
  getTaskList();
};

const handleCurrentChange = (val) => {
  params.value.pageNum = val;
  getTaskList();
};

const currentChange = (val) => {
  currentHeight.value = val;
  getTaskList();
};
</script>

<template>
  <div class="task table-page" :style="isMobile ? undefined : `min-height: calc(320px + ${currentHeight}px)`">
    <div class="top-box">
      <el-button type="primary" :icon="Back" size="small" @click="goback">{{ $t("common.back") }}</el-button>
      <div class="top-box-title">{{ $t("task.jobDetail") }}</div>
      <menuRefresh :loading="loading" :autoRefresh="false" :needShow="1" @getData="getTaskList" />
    </div>
    <taskCurrent @currentChange="currentChange" class="task-current" :style="`height: ${currentHeight}px;`" :jobId="String(params.id || '')" />
    <div class="table-box" :style="`height: calc(100% - 117px - ${currentHeight}px);`">
      <el-table class="task-table" :data="taskData.dataList" height="100%" v-loading="loading" :empty-text="$t('task.noTask')">
        <el-table-column type="index" :label="$t('task.serial')" align="center" width="70" />
        <el-table-column prop="status" :label="$t('task.status')" width="140">
          <template #default="scope">
            <div :class="`bg-status bg-${scope.row.status < 6 ? scope.row.status : 7}`">
              <template v-if="scope.row.status == 1 && scope.row.allNum == 0">
                {{ $t("task.scanning") }}
              </template>
              <template v-else-if="scope.row.status == 2 && scope.row.allNum == 0">
                {{ $t("task.noNeedSync") }}
              </template>
              <template v-else>
                <span v-if="scope.row.status != 6">{{ taskStatus(scope.row.status) }}</span>
                <el-popover v-else placement="top-end" :title="$t('common.reason')" width="220" trigger="hover" :content="scope.row.errMsg">
                  <template #reference>
                    <span>{{ $t("taskDetail.failedReason") }}</span>
                  </template>
                </el-popover>
              </template>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="successNum" :label="$t('task.progress')">
          <template #default="scope">
            <span v-if="scope.row.status == 1">{{ $t("task.syncingProgress") }}</span>
            <div class="progress-list" v-else>
              <span class="prg-num bg-8">{{ scope.row.allNum }}</span>
              <span class="prg-num bg-2">{{ scope.row.successNum }}</span>
              <span class="prg-num bg-7">{{ scope.row.failNum }}</span>
              <span class="prg-num bg-3">{{ scope.row.otherNum }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="createTime" :label="$t('common.createdAt')" width="170">
          <template #default="scope">
            {{ parseTime(scope.row.createTime) }}
          </template>
        </el-table-column>
        <el-table-column :label="$t('common.operate')" width="210">
          <template #default="scope">
            <el-button type="danger" :icon="Delete" @click="delTask(scope.row.id)" :loading="btnLoading" :disabled="scope.row.status == 1" size="small">
              {{ scope.row.status == 1 ? $t("task.deleteUnavailable") : $t("common.delete") }}
            </el-button>
            <el-button type="primary" :icon="View" @click="detail(scope.row.id)" :loading="btnLoading" size="small" v-if="scope.row.allNum != 0">
              {{ $t("home.detail") }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <div class="page">
      <div class="page-tip">
        <span class="legend-title">{{ $t("task.legend") }}:</span>
        <span class="prg-num bg-8">{{ $t("task.total") }}</span>
        <span class="prg-num bg-2">{{ $t("task.success") }}</span>
        <span class="prg-num bg-7">{{ $t("task.fail") }}</span>
        <span class="prg-num bg-3">{{ $t("task.other") }}</span>
      </div>
      <el-pagination
        v-model:current-page="params.pageNum"
        v-model:page-size="params.pageSize"
        :total="taskData.count"
        :layout="isMobile ? 'prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
        :page-sizes="[10, 20, 50, 100]"
        @size-change="handleSizeChange"
        @current-change="handleCurrentChange"
      />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.task {
  overflow-y: auto;

  .task-current,
  .table-box {
    transition: height 0.5s ease;
  }

  .progress-list,
  .page-tip {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
  }

  .legend-title {
    margin-right: 12px;
    color: var(--text-secondary);
  }

  .prg-num {
    font-size: 13px;
    padding: 1px 6px;
    text-align: center;
    font-weight: 700;
    margin: 2px 3px;
    min-width: 56px;
    border-radius: 4px;
  }

  .page {
    align-items: center;
    justify-content: space-between;
  }
}

@media (max-width: 768px) {
  .task {
    height: auto;
    min-height: 100%;
    overflow-y: visible;

    .top-box {
      .top-box-title {
        order: 0;
      }

      > .el-button {
        order: 1;
      }

      :deep(.menu-refresh) {
        order: 2;
        margin-left: auto;
      }
    }

    .table-box {
      height: 420px !important;
      min-height: 420px;
    }

    .page {
      flex-direction: column;
      align-items: stretch;
      gap: 10px;
    }

    .page-tip {
      justify-content: center;
    }
  }
}
</style>
