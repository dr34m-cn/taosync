<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { alistGet, jobDelete, jobGetJob, jobPost, jobPut } from "@/api/job";
import fileSizeFilter from "./components/fileSizeFilter.vue";
import pathSelect from "./components/pathSelect.vue";
import menuRefresh from "./components/menuRefresh.vue";
import { parseSize, parseTime } from "@/utils/utils";
import { isFileSizeBoundaryValid, isFileSizeRangeValid } from "@/utils/fileSizeFilter";
import { ElMessage, ElMessageBox } from "element-plus";
import { CaretRight, Plus, View } from "@element-plus/icons-vue";
import { useI18n } from "vue-i18n";
import { useMediaQuery } from "@vueuse/core";

const router = useRouter();
const { t } = useI18n();
const isMobile = useMediaQuery("(max-width: 768px)");

const jobData = ref({
  dataList: [],
  count: 0,
});
const params = ref({
  pageSize: 10,
  pageNum: 1,
});
const alistList = ref([]);
const cronList = ref([
  { key: "year", place: "2024" },
  { key: "month", place: "1-12" },
  { key: "day", place: "1-31" },
  { key: "week", place: "1-53" },
  { key: "day_of_week", place: "0-6 or mon,tue,wed,thu,fri,sat,sun" },
  { key: "hour", place: "0-23" },
  { key: "minute", place: "0-59" },
  { key: "second", place: "0-59" },
  { key: "start_date", place: "2000-01-01" },
  { key: "end_date", place: "2040-12-31" },
]);
const cuIsSrc = ref(false);
const loading = ref(false);
const btnLoading = ref(false);
const editLoading = ref(false);
const editData = ref(null);
const excludeTmp = ref("");
const editShow = ref(false);
const disableShow = ref(false);
const disableIsDel = ref(false);
const disableCu = ref({
  id: null,
  pause: true,
});
const jobRule = ref();
const pathSelectRef = ref();

const validateFileSizeRange = (_rule, _value, callback) => {
  const minFileSize = editData.value?.minFileSize ?? null;
  const maxFileSize = editData.value?.maxFileSize ?? null;
  if (!isFileSizeBoundaryValid(minFileSize) || !isFileSizeBoundaryValid(maxFileSize)) {
    callback(new Error(t("home.fileSizeInvalid")));
    return;
  }
  if (!isFileSizeRangeValid(minFileSize, maxFileSize)) {
    callback(new Error(t("home.fileSizeRangeInvalid")));
    return;
  }
  callback();
};

const addRule = computed(() => ({
  srcPath: [
    {
      required: true,
      message: t("home.requiredSource"),
      trigger: "change",
    },
  ],
  dstPath: [
    {
      type: "array",
      required: true,
      message: t("home.requiredTarget"),
      trigger: "change",
    },
  ],
  alistId: [
    {
      type: "number",
      required: true,
      message: t("home.requiredEngine"),
      trigger: "change",
    },
  ],
  scanIntervalT: [
    {
      required: true,
      pattern: /^(0|[1-9]\d*)$/,
      message: t("home.nonNegativeInt"),
      trigger: "blur",
    },
  ],
  scanIntervalS: [
    {
      required: true,
      pattern: /^(0|[1-9]\d*)$/,
      message: t("home.nonNegativeInt"),
      trigger: "blur",
    },
  ],
  maxFileSize: [
    {
      validator: validateFileSizeRange,
      trigger: "change",
    },
  ],
}));

const methodText = (val) => {
  if (val === 0) return t("home.onlyAdd");
  if (val === 1) return t("home.fullSync");
  return t("home.moveMode");
};

const engineOptionLabel = (engine) => {
  if (engine.engineType === "taosync") return engine.displayName || "TaoSync";
  const name = engine.url || engine.displayName || engine.userName || t("engine.alist");
  return `${name}${engine.remark ? ` [${engine.remark}]` : ""}`;
};

const engineOptionMeta = (engine) => (engine.engineType === "taosync" ? t("engine.internal") : engine.userName);

const cronText = (val) => {
  if (val === 0) return t("home.intervalCall");
  if (val === 1) return t("home.cronCall");
  return t("home.manualOnly");
};

const sizeFilterText = (job) => {
  const minFileSize = job.minFileSize ?? null;
  const maxFileSize = job.maxFileSize ?? null;
  if (minFileSize !== null && maxFileSize !== null) {
    return t("home.fileSizeBetween", { min: parseSize(minFileSize), max: parseSize(maxFileSize) });
  }
  if (minFileSize !== null) return t("home.fileSizeAtLeast", { size: parseSize(minFileSize) });
  if (maxFileSize !== null) return t("home.fileSizeAtMost", { size: parseSize(maxFileSize) });
  return t("home.noLimit");
};

const getJobList = () => {
  loading.value = true;
  jobGetJob(params.value)
    .then((res) => {
      jobData.value = res.data;
    })
    .finally(() => {
      loading.value = false;
    });
};

const getAlistList = () => {
  return alistGet().then((res) => {
    alistList.value = res.data;
  });
};

const runAllJob = () => {
  ElMessageBox.confirm(t("home.runAllConfirm"), t("common.tips"), {
    confirmButtonText: t("common.confirm"),
    cancelButtonText: t("common.cancel"),
    type: "warning",
  }).then(() => {
    btnLoading.value = true;
    jobPut({
      pause: null,
    })
      .then((res) => {
        ElMessage({
          message: res.msg,
          type: "success",
        });
      })
      .finally(() => {
        btnLoading.value = false;
      });
  });
};

const selectPath = (isSrc) => {
  cuIsSrc.value = isSrc;
  pathSelectRef.value.show();
};

const changeEngine = () => {
  if (!editData.value) return;
  editData.value.srcPath = "";
  editData.value.dstPath = [];
};

const toCron = () => {
  window.open("https://dr34m.cn/2024/08/newpost-58/", "_blank");
};

const toIgnore = () => {
  window.open("https://dr34m.cn/2024/09/newpost-60/", "_blank");
};

const putJob = (row, pause = null) => {
  if (row.enable !== 1 && pause !== false) {
    ElMessage.error(t("home.disabledRunTip"));
    return;
  }
  btnLoading.value = true;
  jobPut({
    id: row.id,
    pause,
  })
    .then((res) => {
      ElMessage({
        message: res.msg,
        type: "success",
      });
      if (pause !== false) {
        detail(row.id);
      } else {
        getJobList();
      }
    })
    .finally(() => {
      btnLoading.value = false;
    });
};

const disableJobShow = (row, isDel) => {
  disableIsDel.value = isDel;
  disableCu.value.id = row.id;
  disableShow.value = true;
};

const editJobShow = (row) => {
  if (row.enable && row.isCron !== 2) {
    ElMessage.error(t("home.editDisabledTip"));
    return;
  }
  if (alistList.value.length === 0) {
    getAlistList();
  }
  excludeTmp.value = "";
  editData.value = JSON.parse(JSON.stringify(row));
  editData.value.dstPath = editData.value.dstPath.split(":");
  editData.value.exclude = editData.value.exclude ? editData.value.exclude.split(":") : [];
  editData.value.minFileSize = editData.value.minFileSize ?? null;
  editData.value.maxFileSize = editData.value.maxFileSize ?? null;
  editData.value.sourceMode = Number(editData.value.sourceMode) === 1 ? 1 : 0;
  editShow.value = true;
};

const addShow = () => {
  if (alistList.value.length === 0) {
    getAlistList();
  }
  const nextEditData = {
    enable: 1,
    remark: "",
    srcPath: "",
    dstPath: [],
    alistId: null,
    useCacheT: 1,
    scanIntervalT: 1,
    useCacheS: 0,
    scanIntervalS: 0,
    method: 0,
    sourceMode: 0,
    interval: 1440,
    isCron: 0,
    exclude: [],
    minFileSize: null,
    maxFileSize: null,
  };
  cronList.value.forEach((item) => {
    nextEditData[item.key] = null;
  });
  editData.value = nextEditData;
  excludeTmp.value = "";
  editShow.value = true;
};

const closeShow = () => {
  jobRule.value?.clearValidate();
  editShow.value = false;
};

const closeDisableShow = () => {
  disableShow.value = false;
  disableCu.value = {
    id: null,
    pause: true,
  };
};

const addExclude = () => {
  if (excludeTmp.value !== "") {
    editData.value.exclude.push(excludeTmp.value);
  }
  excludeTmp.value = "";
};

const delExclude = (index) => {
  editData.value.exclude.splice(index, 1);
};

const delDstPath = (index) => {
  editData.value.dstPath.splice(index, 1);
};

const submit = () => {
  jobRule.value.validate((valid) => {
    if (!valid) return;
    const postData = JSON.parse(JSON.stringify(editData.value));
    for (const key in postData) {
      if (postData[key] === "") {
        postData[key] = null;
      }
    }
    if (postData.isCron === 0 && postData.interval == null) {
      ElMessage.error(t("home.intervalRequired"));
      return;
    }
    if (postData.isCron === 1) {
      let flag = 0;
      cronList.value.forEach((item) => {
        if (postData[item.key] != null) {
          flag += 1;
        }
      });
      if (flag === 0) {
        ElMessage.error(t("home.cronRequired"));
        return;
      }
    }
    postData.dstPath = postData.dstPath.join(":");
    postData.exclude = postData.exclude.join(":");
    postData.sourceMode = Number(postData.sourceMode) === 1 ? 1 : 0;
    editLoading.value = true;
    jobPost(postData)
      .then((res) => {
        ElMessage({
          message: res.msg,
          type: "success",
        });
        closeShow();
        getJobList();
      })
      .finally(() => {
        editLoading.value = false;
      });
  });
};

const submitDisable = () => {
  editLoading.value = true;
  const request = disableIsDel.value ? jobDelete(disableCu.value) : jobPut(disableCu.value);
  request
    .then((res) => {
      ElMessage({
        message: res.msg,
        type: "success",
      });
      getJobList();
      closeDisableShow();
    })
    .finally(() => {
      editLoading.value = false;
    });
};

const submitPath = (path) => {
  if (cuIsSrc.value) {
    editData.value.srcPath = path;
  } else if (editData.value.dstPath.includes(path)) {
    ElMessage.error(t("home.excludeExists"));
  } else {
    editData.value.dstPath.push(path);
  }
};

const detail = (jobId) => {
  router.push({
    path: "/home/task",
    query: {
      jobId,
    },
  });
};

const handleSizeChange = (val) => {
  params.value.pageSize = val;
  getJobList();
};

const handleCurrentChange = (val) => {
  params.value.pageNum = val;
  getJobList();
};

onMounted(() => {
  getJobList();
});
</script>

<template>
  <div class="home table-page">
    <div class="top-box">
      <div class="top-box-left">
        <el-button type="success" :icon="Plus" @click="addShow" size="small">{{ $t("home.newJob") }}</el-button>
        <el-button
          @click="runAllJob"
          size="small"
          v-if="jobData.dataList.length > 1"
          :icon="CaretRight"
          :loading="btnLoading"
          type="primary"
        >
          {{ $t("home.runAll") }}
        </el-button>
      </div>
      <div class="top-box-title">{{ $t("home.jobManagement") }}</div>
      <menuRefresh :autoRefresh="false" :freshInterval="5273" :loading="loading" @getData="getJobList" />
    </div>

    <el-table class="job-table" :data="jobData.dataList" height="calc(100% - 117px)" v-loading="loading">
      <el-table-column type="expand">
        <template #default="props">
          <div class="form-box">
            <div class="form-box-item">
              <div class="form-box-item-label">{{ $t("home.methodView") }}</div>
              <div class="form-box-item-value">{{ methodText(props.row.method) }}</div>
            </div>
            <div class="form-box-item">
              <div class="form-box-item-label">{{ $t("home.targetScan") }}</div>
              <div class="form-box-item-value">
                {{ props.row.useCacheT == 0 ? $t("home.noCache") : $t("home.useCache") }}，{{
                  $t("home.operateInterval", { seconds: props.row.scanIntervalT })
                }}
              </div>
            </div>
            <div class="form-box-item">
              <div class="form-box-item-label">{{ $t("home.sourceScan") }}</div>
              <div class="form-box-item-value">
                {{ props.row.useCacheS == 0 ? $t("home.noCache") : $t("home.useCache") }}，{{
                  $t("home.operateInterval", { seconds: props.row.scanIntervalS })
                }}
              </div>
            </div>
            <div class="form-box-item">
              <div class="form-box-item-label">{{ $t("home.callType") }}</div>
              <div class="form-box-item-value">{{ cronText(props.row.isCron) }}</div>
            </div>
            <div class="form-box-item" v-if="props.row.isCron == 0">
              <div class="form-box-item-label">{{ $t("home.syncInterval") }}</div>
              <div class="form-box-item-value">{{ props.row.interval }} {{ $t("home.minute") }}</div>
            </div>
            <template v-else-if="props.row.isCron == 1">
              <div class="form-box-item" v-for="item in cronList" :key="item.key">
                <div class="form-box-item-label">{{ item.key }}</div>
                <div class="form-box-item-value">{{ props.row[item.key] || "-" }}</div>
              </div>
            </template>
            <div class="form-box-item">
              <div class="form-box-item-label">{{ $t("home.excludeRules") }}</div>
              <div class="form-box-item-value">
                <span v-if="props.row.exclude == null">-</span>
                <template v-else>
                  <span class="label-chip bg-3" v-for="item in props.row.exclude.split(':')" :key="item">{{ item }}</span>
                </template>
              </div>
            </div>
            <div class="form-box-item">
              <div class="form-box-item-label">{{ $t("home.fileSizeFilter") }}</div>
              <div class="form-box-item-value">{{ sizeFilterText(props.row) }}</div>
            </div>
            <div class="form-box-item">
              <div class="form-box-item-label">{{ $t("common.createdAt") }}</div>
              <div class="form-box-item-value">{{ parseTime(props.row.createTime) }}</div>
            </div>
            <div class="form-box-item">
              <div class="form-box-item-label">{{ $t("home.more") }}</div>
              <div class="form-box-item-value action-line">
                <template v-if="props.row.isCron != 2">
                  <el-button type="warning" :loading="btnLoading" size="small" v-if="props.row.enable" @click="disableJobShow(props.row, false)">
                    {{ $t("common.disable") }}
                  </el-button>
                  <el-button type="success" :loading="btnLoading" size="small" v-else @click="putJob(props.row, false)">
                    {{ $t("common.enable") }}
                  </el-button>
                </template>
                <el-button type="danger" :loading="btnLoading" size="small" @click="disableJobShow(props.row, true)">
                  {{ $t("common.delete") }}
                </el-button>
                <el-button type="primary" :loading="btnLoading" size="small" @click="editJobShow(props.row)">
                  {{ $t("common.edit") }}
                </el-button>
              </div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="remark" :label="$t('home.jobName')" width="130">
        <template #default="scope">
          {{ scope.row.remark || "--" }}
        </template>
      </el-table-column>
      <el-table-column prop="enable" :label="$t('home.status')" width="90">
        <template #default="scope">
          <div :class="`bg-status bg-${scope.row.enable ? '2' : '7'}`">
            {{ scope.row.enable ? $t("common.enabled") : $t("common.disabled") }}
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="srcPath" :label="$t('home.sourcePath')" min-width="120">
        <template #default="scope">
          <div class="path-list">
            <div class="path-box bg-8">{{ scope.row.srcPath }}</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="dstPath" :label="$t('home.targetPath')" min-width="180">
        <template #default="scope">
          <div class="path-list">
            <div class="path-box bg-1" v-for="item in scope.row.dstPath.split(':')" :key="item">{{ item }}</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column :label="$t('common.operate')" align="center" width="230">
        <template #default="scope">
          <el-button :icon="CaretRight" type="primary" @click="putJob(scope.row)" :loading="btnLoading" size="small">
            {{ $t("home.manualRun") }}
          </el-button>
          <el-button :icon="View" type="success" @click="detail(scope.row.id)" :loading="btnLoading" size="small">
            {{ $t("home.detail") }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="page-box">
      <el-pagination
        v-model:current-page="params.pageNum"
        v-model:page-size="params.pageSize"
        :total="jobData.count"
        :layout="isMobile ? 'prev, pager, next' : 'total, sizes, prev, pager, next, jumper'"
        :page-sizes="[10, 20, 50, 100]"
        @size-change="handleSizeChange"
        @current-change="handleCurrentChange"
      />
    </div>

    <el-dialog
      class="job-dialog"
      top="5vh"
      :close-on-click-modal="false"
      v-model="editShow"
      :append-to-body="true"
      :title="editData && editData.id != null ? $t('home.editJob') : $t('home.addJob')"
      width="820px"
    >
      <div class="elform-box">
        <el-form :model="editData" :rules="addRule" ref="jobRule" v-if="editShow" label-width="150px">
          <div class="job-form-grid">
          <el-form-item prop="enable" :label="$t('common.enabled')">
            <div class="label-width">
              <el-switch v-model="editData.enable" :active-value="1" :inactive-value="0" v-if="editData.isCron != 2" />
              <span v-else>{{ $t("common.enabled") }}</span>
            </div>
          </el-form-item>
          <el-form-item prop="alistId" :label="$t('home.engine')">
            <el-select v-model="editData.alistId" :placeholder="$t('home.requiredEngine')" class="label-width" :no-data-text="$t('home.noEngine')" @change="changeEngine">
              <el-option v-for="item in alistList" :key="item.id" :label="engineOptionLabel(item)" :value="item.id">
                <span class="option-left">{{ engineOptionLabel(item) }}</span>
                <span class="option-right">{{ engineOptionMeta(item) }}</span>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item prop="srcPath" :label="$t('home.srcPath')">
            <div v-if="editData.alistId == null" class="label-width">{{ $t("home.selectEngineFirst") }}</div>
            <div v-else class="label-width">
              {{ editData.srcPath }}
              <el-button type="primary" size="small" :style="`margin-left: ${editData.srcPath == '' ? 0 : 12}px;`" @click="selectPath(true)">
                {{ editData.srcPath == "" ? $t("common.select") : $t("common.change") }}{{ $t("home.selectDir") }}
              </el-button>
            </div>
          </el-form-item>
          <el-form-item prop="dstPath" :label="$t('home.dstPath')">
            <div v-if="editData.alistId == null" class="label-width">{{ $t("home.selectEngineFirst") }}</div>
            <div v-else class="label-width">
              <div class="label-list-box">
                <div v-for="(item, index) in editData.dstPath" :key="item" class="label-list-item">
                  <div class="bg-1 label-list-item-left">{{ item }}</div>
                  <el-button type="danger" size="small" @click="delDstPath(index)">{{ $t("home.deleteDir") }}</el-button>
                </div>
                <el-button type="primary" size="small" @click="selectPath(false)">
                  {{ editData.dstPath.length == 0 ? $t("common.select") : $t("common.add") }}{{ $t("home.selectDir") }}
                </el-button>
              </div>
            </div>
          </el-form-item>
          <el-form-item prop="remark" :label="$t('home.jobRemark')">
            <div class="label-width">
              <el-input v-model="editData.remark" :placeholder="$t('home.jobRemarkPlaceholder')" />
            </div>
          </el-form-item>
          <el-form-item prop="method" :label="$t('home.method')">
            <el-select v-model="editData.method" class="label-width">
              <el-option :label="$t('home.onlyAdd')" :value="0">
                <span class="option-left">{{ $t("home.onlyAdd") }}</span>
                <span class="option-right">{{ $t("home.onlyAddTip") }}</span>
              </el-option>
              <el-option :label="$t('home.fullSync')" :value="1">
                <span class="option-left">{{ $t("home.fullSync") }}</span>
                <span class="option-right">{{ $t("home.fullSyncTip") }}</span>
              </el-option>
              <el-option :label="$t('home.moveMode')" :value="2">
                <span class="option-left">{{ $t("home.moveMode") }}</span>
                <span class="option-right">{{ $t("home.moveModeTip") }}</span>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item prop="sourceMode" :label="$t('home.sourceMode')">
            <div class="label-width source-mode-control">
              <el-switch v-model="editData.sourceMode" :active-value="1" :inactive-value="0" />
              <div class="source-mode-tip">{{ $t("home.sourceModeTip") }}</div>
            </div>
          </el-form-item>
          <el-form-item prop="useCacheT" :label="$t('home.targetCache')">
            <el-select v-model="editData.useCacheT" class="label-width">
              <el-option :label="$t('home.cacheDisabled')" :value="0" />
              <el-option :label="$t('home.cacheEnabled')" :value="1" />
            </el-select>
          </el-form-item>
          <el-form-item prop="scanIntervalT" :label="$t('home.targetInterval')">
            <el-input v-model.number="editData.scanIntervalT" class="label-width">
              <template #append>{{ $t("home.second") }}</template>
            </el-input>
          </el-form-item>
          <el-form-item prop="useCacheS" :label="$t('home.sourceCache')">
            <el-select v-model="editData.useCacheS" class="label-width">
              <el-option :label="$t('home.cacheDisabled')" :value="0" />
              <el-option :label="$t('home.cacheEnabled')" :value="1" />
            </el-select>
          </el-form-item>
          <el-form-item prop="scanIntervalS" :label="$t('home.sourceInterval')">
            <el-input v-model.number="editData.scanIntervalS" class="label-width">
              <template #append>{{ $t("home.second") }}</template>
            </el-input>
          </el-form-item>
          <el-form-item prop="exclude" :label="$t('home.excludeSyntax')">
            <div class="label-width">
              {{ $t("home.excludeSyntaxTip") }}<br />
              <span @click="toIgnore" class="to-link">{{ $t("home.excludeGuide") }}</span>
            </div>
          </el-form-item>
          <el-form-item prop="exclude" :label="$t('home.excludeRules')">
            <div class="label-width">
              <div class="label-list-box">
                <el-input v-model="excludeTmp" :placeholder="$t('home.excludePlaceholder')">
                  <template #append>
                    <el-button @click="addExclude">{{ $t("common.add") }}</el-button>
                  </template>
                </el-input>
                <div v-for="(item, index) in editData.exclude" :key="item" class="label-list-item">
                  <div class="bg-3 label-list-item-left">{{ item }}</div>
                  <el-button type="danger" size="small" @click="delExclude(index)">{{ $t("common.delete") }}</el-button>
                </div>
              </div>
            </div>
          </el-form-item>
          <el-form-item prop="maxFileSize" :label="$t('home.fileSizeFilter')" class="size-filter-form-item">
            <file-size-filter
              v-model:min-file-size="editData.minFileSize"
              v-model:max-file-size="editData.maxFileSize"
            />
          </el-form-item>
          <div v-if="editData.method == 2" class="move-warning">{{ $t("home.moveWarning") }}</div>
          <el-form-item prop="isCron" :label="$t('home.callType')">
            <el-select v-model="editData.isCron" class="label-width">
              <el-option :label="$t('home.intervalCall')" :value="0">
                <span class="option-left">{{ $t("home.intervalCall") }}</span>
                <span class="option-right">{{ $t("home.intervalCallTip") }}</span>
              </el-option>
              <el-option :label="$t('home.cronCall')" :value="1">
                <span class="option-left">{{ $t("home.cronCall") }}</span>
                <span class="option-right">{{ $t("home.cronCallTip") }}</span>
              </el-option>
              <el-option :label="$t('home.manualOnly')" :value="2">
                <span class="option-left">{{ $t("home.manualOnly") }}</span>
                <span class="option-right">{{ $t("home.manualOnlyTip") }}</span>
              </el-option>
            </el-select>
          </el-form-item>
          <template v-if="editData.isCron == 0">
            <el-form-item prop="interval" :label="$t('home.syncInterval')">
              <el-input v-model.number="editData.interval" class="label-width">
                <template #append>{{ $t("home.minute") }}</template>
              </el-input>
            </el-form-item>
            <div class="form-tip">{{ $t("home.intervalTip") }}</div>
          </template>
          <template v-else-if="editData.isCron == 1">
            <el-form-item prop="isCron" :label="$t('common.tips')">
              <div class="label-width">
                <span @click="toCron" class="to-link">{{ $t("home.cronGuide") }}</span>
              </div>
            </el-form-item>
            <el-form-item v-for="item in cronList" :key="item.key" :prop="item.key" :label="item.key">
              <el-input v-model="editData[item.key]" :placeholder="item.place" class="label-width" />
            </el-form-item>
          </template>
          </div>
        </el-form>
      </div>
      <template #footer>
        <el-button @click="closeShow">{{ $t("common.cancel") }}</el-button>
        <el-button type="primary" @click="submit" :loading="editLoading">{{ $t("common.confirm") }}</el-button>
      </template>
    </el-dialog>

    <el-dialog :close-on-click-modal="false" v-model="disableShow" :append-to-body="true" :title="$t('common.warning')" width="460px">
      <div class="danger-tip">
        {{ disableIsDel ? $t("home.deleteJobConfirm") : $t("home.disableJobConfirm") }}
      </div>
      <template #footer>
        <el-button @click="closeDisableShow">{{ $t("common.cancel") }}</el-button>
        <el-button type="primary" @click="submitDisable" :loading="editLoading">{{ $t("common.confirm") }}</el-button>
      </template>
    </el-dialog>

    <pathSelect v-if="editData" :alistId="editData.alistId" ref="pathSelectRef" @submit="submitPath" />
  </div>
</template>

<style lang="scss" scoped>
.home {
  .top-box-left,
  .action-line {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .label-chip {
    display: inline-block;
    margin-right: 6px;
    margin-bottom: 4px;
  }
}

:global(.job-dialog) {
  max-width: calc(100vw - 24px);
}

:global(.job-dialog .el-dialog__body) {
  padding: 12px 20px 4px;
}

:global(.job-dialog .elform-box) {
  max-height: calc(90vh - 150px);
  overflow-x: hidden;
  overflow-y: auto;
  padding-right: 4px;
}

:global(.job-dialog .job-form-grid) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: flex-start;
  column-gap: 0;
}

:global(.job-dialog .el-form-item) {
  min-width: 0;
  margin-bottom: 14px;
}

:global(.job-dialog .size-filter-form-item) {
  grid-column: 1 / -1;
}

:global(.job-dialog .size-filter-form-item .el-form-item__content) {
  min-width: 0;
}

:global(.job-dialog .label-width) {
  width: 220px;
  min-height: 32px;
}

:global(.job-dialog .source-mode-control) {
  height: auto;
}

:global(.job-dialog .source-mode-tip) {
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

:global(.job-dialog .label-list-box) {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  min-height: 42px;
}

:global(.job-dialog .label-list-item) {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  margin: 4px 12px 4px 0;
}

:global(.job-dialog .label-list-item-left) {
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 3px;
  padding: 0 6px;
  line-height: 20px;
  margin-right: -4px;
}

:global(.job-dialog .label-list-item .el-button) {
  border-radius: 0 3px 3px 0;
}

:global(.job-dialog .to-link) {
  color: var(--active-color);
  text-decoration: underline;
  cursor: pointer;
}

:global(.option-left) {
  float: left;
  margin-right: 16px;
}

:global(.option-right) {
  float: right;
  color: var(--text-muted);
  font-size: 13px;
}

:global(.job-dialog .move-warning),
:global(.job-dialog .form-tip) {
  grid-column: 1 / -1;
  margin: -4px 0 16px 150px;
  color: var(--fail-color);
  font-weight: 700;
}

:global(.job-dialog .form-tip) {
  color: var(--text-muted);
  font-weight: 400;
}

:global(.danger-tip) {
  color: var(--fail-color);
  font-weight: 700;
  text-align: center;
  font-size: 18px;
}

@media (max-width: 860px) {
  :global(.job-dialog .job-form-grid) {
    display: block;
  }

  :global(.job-dialog .label-width) {
    width: 100%;
  }

  :global(.job-dialog .move-warning),
  :global(.job-dialog .form-tip) {
    margin-left: 0;
  }
}

@media (max-width: 768px) {
  .home {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;

    .top-box {
      flex: 0 0 auto;

      .top-box-left {
        order: 1;
        flex: 1;
        min-width: 0;
        flex-wrap: wrap;
      }

      .top-box-title {
        order: 0;
      }

      :deep(.menu-refresh) {
        order: 2;
        margin-left: auto;
      }
    }

    .job-table {
      flex: 1;
      min-height: 280px;
      height: auto !important;
    }

    .page-box {
      flex: 0 0 auto;
      margin-top: 10px;
    }

    .action-line {
      flex-wrap: wrap;
    }
  }

  :global(.job-dialog .elform-box) {
    max-height: calc(100vh - 154px);
    padding-right: 0;
  }

  :global(.job-dialog .label-list-box) {
    align-items: stretch;
  }

  :global(.job-dialog .label-list-item) {
    width: 100%;
    max-width: 100%;
    margin-right: 0;
  }

  :global(.job-dialog .label-list-item-left) {
    flex: 1;
    max-width: none;
  }

  :global(.job-dialog .el-input-group__append) {
    padding: 0 10px;
  }

  :global(.el-select-dropdown__item .option-left) {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  :global(.el-select-dropdown__item .option-right) {
    display: none;
  }
}
</style>
