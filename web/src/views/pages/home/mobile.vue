<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { CaretRight, CircleCheck, CircleClose, Delete, Edit, Plus, View } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { alistGet, jobDelete, jobGetJob, jobPost, jobPut } from "@/api/job";
import { parseSize, parseTime } from "@/utils/utils";
import { isFileSizeBoundaryValid, isFileSizeRangeValid } from "@/utils/fileSizeFilter";
import fileSizeFilter from "./components/fileSizeFilter.vue";
import menuRefresh from "./components/menuRefresh.vue";
import pathSelect from "./components/pathSelect.vue";

const router = useRouter();
const { t } = useI18n();

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

const loading = ref(false);
const btnLoading = ref(false);
const editLoading = ref(false);
const editShow = ref(false);
const editData = ref(null);
const excludeTmp = ref("");
const currentPathType = ref("source");
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

const methodText = (value) => {
  if (value === 0) return t("home.onlyAdd");
  if (value === 1) return t("home.fullSync");
  return t("home.moveMode");
};

const cronText = (value) => {
  if (value === 0) return t("home.intervalCall");
  if (value === 1) return t("home.cronCall");
  return t("home.manualOnly");
};

const engineOptionLabel = (engine) => {
  if (engine.engineType === "taosync") return engine.displayName || "TaoSync";
  const name = engine.url || engine.displayName || engine.userName || t("engine.alist");
  return `${name}${engine.remark ? ` [${engine.remark}]` : ""}`;
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

const splitPaths = (value) => String(value || "").split(":").filter(Boolean);

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

const ensureAlistList = async () => {
  if (alistList.value.length > 0) return;
  const res = await alistGet();
  alistList.value = res.data;
};

const showSuccess = (res) => {
  ElMessage({
    message: res.msg,
    type: "success",
  });
};

const detail = (jobId) => {
  router.push({
    path: "/home/task",
    query: { jobId },
  });
};

const runAllJob = () => {
  ElMessageBox.confirm(t("home.runAllConfirm"), t("common.tips"), {
    confirmButtonText: t("common.confirm"),
    cancelButtonText: t("common.cancel"),
    type: "warning",
  }).then(() => {
    btnLoading.value = true;
    jobPut({ pause: null })
      .then(showSuccess)
      .finally(() => {
        btnLoading.value = false;
      });
  });
};

const runJob = (row) => {
  if (row.enable !== 1) {
    ElMessage.error(t("home.disabledRunTip"));
    return;
  }
  btnLoading.value = true;
  jobPut({
    id: row.id,
    pause: null,
  })
    .then((res) => {
      showSuccess(res);
      detail(row.id);
    })
    .finally(() => {
      btnLoading.value = false;
    });
};

const setJobEnabled = (row, enabled) => {
  const execute = () => {
    btnLoading.value = true;
    jobPut({
      id: row.id,
      pause: !enabled,
    })
      .then((res) => {
        showSuccess(res);
        getJobList();
      })
      .finally(() => {
        btnLoading.value = false;
      });
  };

  if (enabled) {
    execute();
    return;
  }

  ElMessageBox.confirm(t("home.disableJobConfirm"), t("common.tips"), {
    confirmButtonText: t("common.confirm"),
    cancelButtonText: t("common.cancel"),
    type: "warning",
  }).then(execute);
};

const removeJob = (row) => {
  ElMessageBox.confirm(t("home.deleteJobConfirm"), t("common.tips"), {
    confirmButtonText: t("common.confirm"),
    cancelButtonText: t("common.cancel"),
    type: "warning",
  }).then(() => {
    btnLoading.value = true;
    jobDelete({
      id: row.id,
      pause: true,
    })
      .then((res) => {
        showSuccess(res);
        getJobList();
      })
      .finally(() => {
        btnLoading.value = false;
      });
  });
};

const addShow = async () => {
  await ensureAlistList();
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

const editJobShow = async (row) => {
  if (row.enable && row.isCron !== 2) {
    ElMessage.error(t("home.editDisabledTip"));
    return;
  }
  await ensureAlistList();
  editData.value = JSON.parse(JSON.stringify(row));
  editData.value.dstPath = splitPaths(editData.value.dstPath);
  editData.value.exclude = splitPaths(editData.value.exclude);
  editData.value.minFileSize = editData.value.minFileSize ?? null;
  editData.value.maxFileSize = editData.value.maxFileSize ?? null;
  editData.value.sourceMode = Number(editData.value.sourceMode) === 1 ? 1 : 0;
  excludeTmp.value = "";
  editShow.value = true;
};

const closeEditor = () => {
  jobRule.value?.clearValidate();
  editShow.value = false;
};

const selectPath = (type) => {
  currentPathType.value = type;
  pathSelectRef.value?.show();
};

const changeEngine = () => {
  if (!editData.value) return;
  editData.value.srcPath = "";
  editData.value.dstPath = [];
};

const submitPath = (path) => {
  if (currentPathType.value === "source") {
    editData.value.srcPath = path;
    return;
  }
  if (editData.value.dstPath.includes(path)) {
    ElMessage.error(t("home.excludeExists"));
    return;
  }
  editData.value.dstPath.push(path);
};

const addExclude = () => {
  if (excludeTmp.value !== "" && !editData.value.exclude.includes(excludeTmp.value)) {
    editData.value.exclude.push(excludeTmp.value);
  }
  excludeTmp.value = "";
};

const submit = () => {
  jobRule.value.validate((valid) => {
    if (!valid) return;
    const postData = JSON.parse(JSON.stringify(editData.value));
    for (const key in postData) {
      if (postData[key] === "") postData[key] = null;
    }
    if (postData.isCron === 0 && postData.interval == null) {
      ElMessage.error(t("home.intervalRequired"));
      return;
    }
    if (postData.isCron === 1 && !cronList.value.some((item) => postData[item.key] != null)) {
      ElMessage.error(t("home.cronRequired"));
      return;
    }
    postData.dstPath = postData.dstPath.join(":");
    postData.exclude = postData.exclude.join(":");
    postData.sourceMode = Number(postData.sourceMode) === 1 ? 1 : 0;
    editLoading.value = true;
    jobPost(postData)
      .then((res) => {
        showSuccess(res);
        closeEditor();
        getJobList();
      })
      .finally(() => {
        editLoading.value = false;
      });
  });
};

const handleCurrentChange = (value) => {
  params.value.pageNum = value;
  getJobList();
};

const toCron = () => window.open("https://dr34m.cn/2024/08/newpost-58/", "_blank");
const toIgnore = () => window.open("https://dr34m.cn/2024/09/newpost-60/", "_blank");

onMounted(getJobList);
</script>

<template>
  <div class="mobile-job-page">
    <div class="mobile-job-header">
      <div>
        <h1>{{ $t("home.jobManagement") }}</h1>
        <div class="job-count">{{ $t("home.mobileJobCount", { count: jobData.count }) }}</div>
      </div>
      <menuRefresh :auto-refresh="false" :need-show="1" :loading="loading" @get-data="getJobList" />
    </div>

    <div class="primary-actions">
      <el-button type="primary" :icon="Plus" @click="addShow">{{ $t("home.newJob") }}</el-button>
      <el-button v-if="jobData.count > 1" type="success" :icon="CaretRight" :loading="btnLoading" @click="runAllJob">
        {{ $t("home.runAll") }}
      </el-button>
    </div>

    <div class="job-list" v-loading="loading">
      <div v-if="!loading && jobData.dataList.length === 0" class="mobile-empty">
        <div>{{ $t("home.mobileEmpty") }}</div>
        <el-button type="primary" :icon="Plus" @click="addShow">{{ $t("home.newJob") }}</el-button>
      </div>

      <article v-for="item in jobData.dataList" :key="item.id" class="job-card">
        <div class="job-card-header">
          <div class="job-identity">
            <h2>{{ item.remark || `${$t("home.jobName")} #${item.id}` }}</h2>
            <span>{{ parseTime(item.createTime) }}</span>
          </div>
          <div :class="`job-status ${item.enable ? 'is-enabled' : 'is-disabled'}`">
            {{ item.enable ? $t("common.enabled") : $t("common.disabled") }}
          </div>
        </div>

        <div class="job-meta">
          <div>
            <span>{{ $t("home.methodView") }}</span>
            <strong>{{ methodText(item.method) }}</strong>
          </div>
          <div>
            <span>{{ $t("home.callType") }}</span>
            <strong>{{ cronText(item.isCron) }}</strong>
          </div>
          <div class="size-filter-meta">
            <span>{{ $t("home.fileSizeFilter") }}</span>
            <strong>{{ sizeFilterText(item) }}</strong>
          </div>
        </div>

        <div class="path-section">
          <div class="path-label">{{ $t("home.sourcePath") }}</div>
          <div class="path-chip source-path">{{ item.srcPath }}</div>
        </div>

        <div class="path-section">
          <div class="path-label">{{ $t("home.targetPath") }}</div>
          <div class="path-chip-list">
            <div v-for="path in splitPaths(item.dstPath)" :key="path" class="path-chip target-path">{{ path }}</div>
          </div>
        </div>

        <div class="job-actions">
          <el-button type="primary" :icon="CaretRight" :loading="btnLoading" @click="runJob(item)">{{ $t("home.manualRun") }}</el-button>
          <el-button type="danger" :icon="Delete" :loading="btnLoading" @click="removeJob(item)">{{ $t("common.delete") }}</el-button>
          <el-button :icon="Edit" :loading="btnLoading" @click="editJobShow(item)">{{ $t("common.edit") }}</el-button>
          <el-button
            v-if="item.isCron != 2"
            :type="item.enable ? 'warning' : 'success'"
            :icon="item.enable ? CircleClose : CircleCheck"
            :loading="btnLoading"
            @click="setJobEnabled(item, !item.enable)"
          >
            {{ item.enable ? $t("common.disable") : $t("common.enable") }}
          </el-button>
          <el-button
            type="success"
            :icon="View"
            :loading="btnLoading"
            :class="{ 'full-row-action': item.isCron != 2 }"
            @click="detail(item.id)"
          >
            {{ $t("home.detail") }}
          </el-button>
        </div>
      </article>
    </div>

    <div v-if="jobData.count > params.pageSize" class="mobile-pagination">
      <el-pagination
        v-model:current-page="params.pageNum"
        :page-size="params.pageSize"
        :total="jobData.count"
        layout="prev, pager, next"
        @current-change="handleCurrentChange"
      />
    </div>

    <el-drawer
      v-model="editShow"
      class="mobile-job-drawer"
      direction="rtl"
      size="100%"
      :append-to-body="true"
      :close-on-click-modal="false"
      :title="editData && editData.id != null ? $t('home.editJob') : $t('home.addJob')"
    >
      <el-form v-if="editData" ref="jobRule" :model="editData" :rules="addRule" label-position="top">
        <section class="editor-section">
          <h2>{{ $t("home.mobileBasic") }}</h2>
          <el-form-item :label="$t('common.enabled')" prop="enable">
            <el-switch v-model="editData.enable" :active-value="1" :inactive-value="0" :disabled="editData.isCron == 2" />
          </el-form-item>
          <el-form-item :label="$t('home.engine')" prop="alistId">
            <el-select v-model="editData.alistId" :placeholder="$t('home.requiredEngine')" :no-data-text="$t('home.noEngine')" @change="changeEngine">
              <el-option v-for="item in alistList" :key="item.id" :label="engineOptionLabel(item)" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item :label="$t('home.jobRemark')" prop="remark">
            <el-input v-model="editData.remark" :placeholder="$t('home.jobRemarkPlaceholder')" />
          </el-form-item>
          <el-form-item :label="$t('home.method')" prop="method">
            <el-select v-model="editData.method">
              <el-option :label="$t('home.onlyAdd')" :value="0" />
              <el-option :label="$t('home.fullSync')" :value="1" />
              <el-option :label="$t('home.moveMode')" :value="2" />
            </el-select>
            <div v-if="editData.method == 2" class="field-warning">{{ $t("home.moveWarning") }}</div>
          </el-form-item>
          <el-form-item :label="$t('home.sourceMode')" prop="sourceMode">
            <el-switch v-model="editData.sourceMode" :active-value="1" :inactive-value="0" />
            <div class="field-tip">{{ $t("home.sourceModeTip") }}</div>
          </el-form-item>
        </section>

        <section class="editor-section">
          <h2>{{ $t("home.mobilePaths") }}</h2>
          <el-form-item :label="$t('home.srcPath')" prop="srcPath">
            <div v-if="editData.alistId == null" class="field-placeholder">{{ $t("home.selectEngineFirst") }}</div>
            <div v-else class="path-editor">
              <div class="selected-path">{{ editData.srcPath || $t("home.requiredSource") }}</div>
              <el-button type="primary" @click="selectPath('source')">
                {{ editData.srcPath ? $t("common.change") : $t("common.select") }}{{ $t("home.selectDir") }}
              </el-button>
            </div>
          </el-form-item>
          <el-form-item :label="$t('home.dstPath')" prop="dstPath">
            <div v-if="editData.alistId == null" class="field-placeholder">{{ $t("home.selectEngineFirst") }}</div>
            <template v-else>
              <div v-if="editData.dstPath.length" class="editable-tags">
                <el-tag v-for="(path, index) in editData.dstPath" :key="path" closable @close="editData.dstPath.splice(index, 1)">
                  {{ path }}
                </el-tag>
              </div>
              <div v-else class="field-placeholder">{{ $t("home.mobileNoTargets") }}</div>
              <el-button class="full-width-button" type="primary" plain @click="selectPath('target')">
                {{ editData.dstPath.length ? $t("common.add") : $t("common.select") }}{{ $t("home.selectDir") }}
              </el-button>
            </template>
          </el-form-item>
        </section>

        <section class="editor-section">
          <h2>{{ $t("home.mobileScan") }}</h2>
          <el-form-item :label="$t('home.targetCache')" prop="useCacheT">
            <el-select v-model="editData.useCacheT">
              <el-option :label="$t('home.cacheDisabled')" :value="0" />
              <el-option :label="$t('home.cacheEnabled')" :value="1" />
            </el-select>
          </el-form-item>
          <el-form-item :label="$t('home.targetInterval')" prop="scanIntervalT">
            <el-input v-model.number="editData.scanIntervalT">
              <template #append>{{ $t("home.second") }}</template>
            </el-input>
          </el-form-item>
          <el-form-item :label="$t('home.sourceCache')" prop="useCacheS">
            <el-select v-model="editData.useCacheS">
              <el-option :label="$t('home.cacheDisabled')" :value="0" />
              <el-option :label="$t('home.cacheEnabled')" :value="1" />
            </el-select>
          </el-form-item>
          <el-form-item :label="$t('home.sourceInterval')" prop="scanIntervalS">
            <el-input v-model.number="editData.scanIntervalS">
              <template #append>{{ $t("home.second") }}</template>
            </el-input>
          </el-form-item>
        </section>

        <section class="editor-section">
          <div class="section-title-row">
            <h2>{{ $t("home.mobileExclude") }}</h2>
            <el-link type="primary" @click="toIgnore">{{ $t("home.excludeGuide") }}</el-link>
          </div>
          <el-form-item :label="$t('home.excludeRules')" prop="exclude">
            <el-input v-model="excludeTmp" :placeholder="$t('home.excludePlaceholder')" @keyup.enter="addExclude">
              <template #append>
                <el-button @click="addExclude">{{ $t("common.add") }}</el-button>
              </template>
            </el-input>
            <div v-if="editData.exclude.length" class="editable-tags exclude-tags">
              <el-tag v-for="(rule, index) in editData.exclude" :key="rule" type="warning" closable @close="editData.exclude.splice(index, 1)">
                {{ rule }}
              </el-tag>
            </div>
          </el-form-item>
        </section>

        <section class="editor-section">
          <h2>{{ $t("home.fileSizeFilter") }}</h2>
          <el-form-item prop="maxFileSize" class="mobile-size-filter-item">
            <file-size-filter
              v-model:min-file-size="editData.minFileSize"
              v-model:max-file-size="editData.maxFileSize"
            />
          </el-form-item>
        </section>

        <section class="editor-section">
          <div class="section-title-row">
            <h2>{{ $t("home.mobileTrigger") }}</h2>
            <el-link v-if="editData.isCron == 1" type="primary" @click="toCron">{{ $t("home.cronGuide") }}</el-link>
          </div>
          <el-form-item :label="$t('home.callType')" prop="isCron">
            <el-select v-model="editData.isCron">
              <el-option :label="$t('home.intervalCall')" :value="0" />
              <el-option :label="$t('home.cronCall')" :value="1" />
              <el-option :label="$t('home.manualOnly')" :value="2" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="editData.isCron == 0" :label="$t('home.syncInterval')" prop="interval">
            <el-input v-model.number="editData.interval">
              <template #append>{{ $t("home.minute") }}</template>
            </el-input>
            <div class="field-tip">{{ $t("home.intervalTip") }}</div>
          </el-form-item>
          <div v-else-if="editData.isCron == 1" class="cron-grid">
            <el-form-item v-for="item in cronList" :key="item.key" :label="item.key" :prop="item.key">
              <el-input v-model="editData[item.key]" :placeholder="item.place" />
            </el-form-item>
          </div>
        </section>
      </el-form>

      <template #footer>
        <div class="drawer-footer">
          <el-button @click="closeEditor">{{ $t("common.cancel") }}</el-button>
          <el-button type="primary" :loading="editLoading" @click="submit">{{ $t("common.confirm") }}</el-button>
        </div>
      </template>
    </el-drawer>

    <pathSelect v-if="editData" ref="pathSelectRef" :alist-id="editData.alistId" @submit="submitPath" />
  </div>
</template>

<style lang="scss" scoped>
.mobile-job-page {
  min-height: 100%;
  padding: 14px 12px 24px;
  box-sizing: border-box;
  background: var(--home-background-color);

  .mobile-job-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;

    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.3;
      color: var(--text-primary);
    }

    .job-count {
      margin-top: 4px;
      font-size: 13px;
      color: var(--text-muted);
    }
  }

  .primary-actions {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin: 14px 0;

    .el-button {
      width: 100%;
      margin: 0;
    }
  }

  .job-list {
    min-height: 180px;
  }

  .mobile-empty {
    min-height: 280px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 18px;
    color: var(--text-muted);
    text-align: center;
  }

  .job-card {
    margin-bottom: 12px;
    padding: 14px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    background: var(--home-item-background-color);

    .job-card-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }

    .job-identity {
      min-width: 0;

      h2 {
        margin: 0;
        overflow: hidden;
        font-size: 17px;
        line-height: 1.35;
        color: var(--text-primary);
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      span {
        display: block;
        margin-top: 4px;
        font-size: 12px;
        color: var(--text-muted);
      }
    }

    .job-status {
      flex: 0 0 auto;
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 700;
    }

    .is-enabled {
      color: var(--success-color);
      background: rgba(47, 158, 68, 0.12);
    }

    .is-disabled {
      color: var(--fail-color);
      background: rgba(224, 49, 49, 0.12);
    }

    .job-meta {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin: 14px 0;
      padding: 10px 0;
      border-top: 1px solid var(--border-color);
      border-bottom: 1px solid var(--border-color);

      div {
        min-width: 0;
      }

      span,
      strong {
        display: block;
      }

      span {
        font-size: 12px;
        color: var(--text-muted);
      }

      strong {
        margin-top: 3px;
        overflow: hidden;
        font-size: 14px;
        color: var(--text-primary);
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .size-filter-meta {
        grid-column: 1 / -1;

        strong {
          white-space: normal;
        }
      }
    }

    .path-section + .path-section {
      margin-top: 10px;
    }

    .path-label {
      margin-bottom: 5px;
      font-size: 12px;
      color: var(--text-muted);
    }

    .path-chip-list {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }

    .path-chip {
      max-width: 100%;
      padding: 4px 7px;
      border-radius: 4px;
      box-sizing: border-box;
      overflow-wrap: anywhere;
      font-size: 12px;
    }

    .source-path {
      color: #7048e8;
      background: rgba(112, 72, 232, 0.12);
    }

    .target-path {
      color: var(--active-color);
      background: rgba(37, 99, 235, 0.12);
    }

    .job-actions {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 14px;
      padding-top: 12px;
      border-top: 1px solid var(--border-color);

      .el-button {
        width: 100%;
        margin: 0;
      }

      .full-row-action {
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

:global(.mobile-job-drawer) {
  background: var(--background-color);
}

:global(.mobile-job-drawer .el-drawer__header) {
  min-height: 52px;
  margin-bottom: 0;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color);
  box-sizing: border-box;
  color: var(--text-primary);
}

:global(.mobile-job-drawer .el-drawer__body) {
  padding: 14px 12px 28px;
  overflow-y: auto;
}

:global(.mobile-job-drawer .el-drawer__footer) {
  padding: 10px 12px;
  border-top: 1px solid var(--border-color);
}

:global(.mobile-job-drawer .el-select) {
  width: 100%;
}

:global(.mobile-job-drawer .editor-section) {
  padding: 14px;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  background: var(--home-item-background-color);
}

:global(.mobile-job-drawer .editor-section + .editor-section) {
  margin-top: 12px;
}

:global(.mobile-job-drawer .editor-section h2) {
  margin: 0 0 14px;
  font-size: 16px;
  color: var(--text-primary);
}

:global(.mobile-job-drawer .mobile-size-filter-item) {
  margin-bottom: 0;
}

:global(.mobile-job-drawer .section-title-row) {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

:global(.mobile-job-drawer .section-title-row .el-link) {
  flex: 0 0 auto;
  font-size: 12px;
}

:global(.mobile-job-drawer .path-editor) {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

:global(.mobile-job-drawer .selected-path),
:global(.mobile-job-drawer .field-placeholder) {
  width: 100%;
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--text-secondary);
}

:global(.mobile-job-drawer .field-placeholder) {
  margin-bottom: 8px;
  color: var(--text-muted);
}

:global(.mobile-job-drawer .editable-tags) {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  width: 100%;
  margin-bottom: 10px;
}

:global(.mobile-job-drawer .editable-tags .el-tag) {
  max-width: 100%;
  height: auto;
  min-height: 24px;
  white-space: normal;
}

:global(.mobile-job-drawer .exclude-tags) {
  margin-top: 10px;
  margin-bottom: 0;
}

:global(.mobile-job-drawer .full-width-button) {
  width: 100%;
  margin: 0;
}

:global(.mobile-job-drawer .field-tip),
:global(.mobile-job-drawer .field-warning) {
  margin-top: 7px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-muted);
}

:global(.mobile-job-drawer .field-warning) {
  color: var(--fail-color);
}

:global(.mobile-job-drawer .cron-grid) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 10px;
}

:global(.mobile-job-drawer .drawer-footer) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

:global(.mobile-job-drawer .drawer-footer .el-button) {
  width: 100%;
  margin: 0;
}

@media (max-width: 380px) {
  .mobile-job-page {
    .primary-actions {
      grid-template-columns: minmax(0, 1fr);
    }

    .job-card {
      .job-actions {
        grid-template-columns: minmax(0, 1fr);

        .full-row-action {
          grid-column: auto;
        }
      }
    }
  }

  :global(.mobile-job-drawer .cron-grid) {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
