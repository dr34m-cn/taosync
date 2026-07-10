<script setup>
import { ref } from "vue";
import { parseSize, parseTime } from "@/utils/utils";
import taskItemStatus from "@/utils/taskItemStatus";
import { useMediaQuery } from "@vueuse/core";

defineProps({
  taskItemData: {
    type: Object,
    default: () => ({
      dataList: [],
      count: 0,
    }),
  },
  loading: {
    type: Boolean,
    default: false,
  },
});
const emit = defineEmits(["pageChange"]);
const isMobile = useMediaQuery("(max-width: 768px)");
const params = ref({
  pageSize: 10,
  pageNum: 1,
});

const handleSizeChange = (val) => {
  params.value.pageSize = val;
  emit("pageChange", params.value);
};
const handleCurrentChange = (val) => {
  params.value.pageNum = val;
  emit("pageChange", params.value);
};
</script>

<template>
  <div class="task-detail-table">
    <el-table class="detail-table" :data="taskItemData.dataList" height="calc(100% - 48px)" v-loading="loading" :empty-text="$t('empty')">
      <el-table-column type="expand">
        <template #default="props">
          <div class="form-box">
            <div class="form-box-item" v-if="props.row.type != 1">
              <div class="form-box-item-label">{{ $t("taskDetail.sourcePath") }}</div>
              <div class="form-box-item-value">{{ props.row.srcPath }}</div>
            </div>
            <div class="form-box-item">
              <div class="form-box-item-label">{{ $t("taskDetail.targetPath") }}</div>
              <div class="form-box-item-value">{{ props.row.dstPath }}</div>
            </div>
            <div class="form-box-item">
              <div class="form-box-item-label">{{ $t("common.createdAt") }}</div>
              <div class="form-box-item-value">{{ parseTime(props.row.createTime) }}</div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="fileName" :label="$t('taskDetail.fileName')">
        <template #default="scope">
          {{ scope.row.fileName || scope.row.dstPath }}
        </template>
      </el-table-column>
      <el-table-column prop="fileSize" :label="$t('taskDetail.fileSize')" width="120">
        <template #default="scope">
          {{ parseSize(scope.row.fileSize) }}
        </template>
      </el-table-column>
      <el-table-column prop="type" :label="$t('taskDetail.operateType')" width="110">
        <template #default="scope">
          <div :class="`bg-status bg-${scope.row.type ? '3' : '8'}`">
            {{
              scope.row.type == 0
                ? scope.row.isPath
                  ? $t("taskDetail.create")
                  : $t("taskDetail.copy")
                : scope.row.type == 1
                  ? $t("taskDetail.delete")
                  : $t("taskDetail.move")
            }}
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="status" :label="$t('task.status')" width="140">
        <template #default="scope">
          <div :class="`bg-status bg-${scope.row.status}`" v-if="scope.row.status != 1">
            <span v-if="scope.row.status != 7">{{ taskItemStatus(scope.row.status) }}</span>
            <el-popover v-else placement="top-end" :title="$t('common.reason')" width="240" trigger="hover" :content="scope.row.errMsg">
              <template #reference>
                <span>{{ $t("taskDetail.failedReason") }}</span>
              </template>
            </el-popover>
          </div>
          <el-progress
            v-else
            :stroke-width="20"
            :text-inside="true"
            style="width: 96px"
            :percentage="Number(Number(scope.row.progress || 0).toFixed(3))"
          />
        </template>
      </el-table-column>
    </el-table>
    <div class="page-box">
      <el-pagination
        v-model:current-page="params.pageNum"
        v-model:page-size="params.pageSize"
        :page-sizes="[10, 20, 50, 100]"
        :layout="isMobile ? 'prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
        :total="taskItemData.count"
        @size-change="handleSizeChange"
        @current-change="handleCurrentChange"
      />
    </div>
  </div>
</template>

<style lang="scss" scoped>
.task-detail-table {
  width: 100%;
  height: 100%;
}

@media (max-width: 768px) {
  .task-detail-table {
    min-width: 0;

    .detail-table {
      width: 100%;
    }

    .page-box {
      margin-top: 10px;
    }
  }
}
</style>
