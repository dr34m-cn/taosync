<script setup>
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { jobGetTaskItem } from "@/api/job";
import { taskItemStatusKeys } from "@/utils/taskItemStatus";
import menuRefresh from "./components/menuRefresh.vue";
import taskDetailTable from "./components/taskDetailTable.vue";
import { Back } from "@element-plus/icons-vue";
import { useI18n } from "vue-i18n";

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
        item.progress = parseInt(item.progress || 0);
        item.progress = item.progress < 100 ? item.progress : 100;
      });
      taskItemData.value = res.data;
    })
    .finally(() => {
      loading.value = false;
    });
};

const goback = () => {
  router.go(-1);
};

const pageChange = (val) => {
  params.value.pageSize = val.pageSize;
  params.value.pageNum = val.pageNum;
  getTaskItemList();
};
</script>

<template>
  <div class="task-detail table-page">
    <div class="top-box">
      <div class="top-left">
        <el-button type="primary" :icon="Back" @click="goback" size="small">{{ $t("common.back") }}</el-button>
        <el-select v-model="params.status" :placeholder="$t('taskDetail.filterStatus')" @change="getTaskItemList" clearable class="filter-select">
          <el-option :label="$t(item)" :value="index" v-for="(item, index) in taskItemStatusKeys" :key="item" />
        </el-select>
        <el-select v-model="params.type" :placeholder="$t('taskDetail.filterType')" @change="getTaskItemList" clearable class="type-select">
          <el-option :label="$t('taskDetail.copyCreate')" :value="0" />
          <el-option :label="$t('taskDetail.delete')" :value="1" />
          <el-option :label="$t('taskDetail.move')" :value="2" />
        </el-select>
      </div>
      <div class="top-box-title">{{ t("taskDetail.title") }}</div>
      <menuRefresh :freshInterval="9973" :autoRefresh="false" :loading="loading" :needShow="1" @getData="getTaskItemList" />
    </div>
    <taskDetailTable class="table-page-box" :loading="loading" :taskItemData="taskItemData" @pageChange="pageChange" />
  </div>
</template>

<style lang="scss" scoped>
.task-detail {
  .top-left {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  .filter-select {
    width: 170px;
  }

  .type-select {
    width: 150px;
  }

  .table-page-box {
    width: 100%;
    height: calc(100% - 54px);
  }
}

@media (max-width: 768px) {
  .task-detail {
    height: auto;
    min-height: 100%;

    .top-box {
      align-items: stretch;

      .top-box-title {
        order: 0;
      }

      :deep(.menu-refresh) {
        order: 2;
        align-self: center;
        margin-left: auto;
      }
    }

    .top-left {
      order: 1;
      width: 100%;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;

      > .el-button {
        grid-column: 1 / -1;
        justify-self: start;
      }
    }

    .filter-select,
    .type-select {
      width: 100%;
    }

    .table-page-box {
      height: 520px;
      min-height: 520px;
    }
  }
}

@media (max-width: 420px) {
  .task-detail {
    .top-left {
      grid-template-columns: minmax(0, 1fr);

      > .el-button {
        grid-column: auto;
      }
    }
  }
}
</style>
