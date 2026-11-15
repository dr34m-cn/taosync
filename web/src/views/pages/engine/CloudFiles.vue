<script setup>
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { ArrowUp, Close, Document, Edit, Folder, FolderOpened, RefreshRight, Right } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useI18n } from "vue-i18n";
import { storagePost } from "@/api/job";
import { parseSize } from "@/utils/utils";

const props = defineProps({ modelValue: Boolean, engineId: Number, mount: Object, directories: Array });
const emit = defineEmits(["update:modelValue"]);
const { t } = useI18n();
const path = ref("");
const entries = ref([]);
const loading = ref(false);
const busy = ref(false);
const taskId = ref(null);
const moveEntry = ref(null);
const moveTarget = ref("");
const moveShow = ref(false);
let epoch = 0;
let loadId = 0;
const root = computed(() => "/" + (props.mount?.name || ""));
const roots = computed(() => (props.directories || []).filter(item => item.driverType === "aliyun")
  .map(item => ({ path: "/" + item.name, name: item.name, leaf: false })));
const operation = (action, data = {}) => storagePost({ action, engineId: props.engineId, ...data });
const fullPath = entry => path.value + "/" + entry.name;
const timestamp = value => value == null ? "-" : new Date(typeof value === "number" ? value * 1000 : value).toLocaleString();

async function browse(destination = path.value) {
  const requestId = ++loadId;
  loading.value = true;
  try {
    const res = await operation("fileList", { path: destination });
    if (requestId !== loadId) return;
    entries.value = res.data || [];
    path.value = destination;
  } finally {
    if (requestId === loadId) loading.value = false;
  }
}

watch(() => props.modelValue, visible => {
  ++epoch;
  ++loadId;
  entries.value = [];
  moveShow.value = false;
  if (visible) {
    path.value = root.value;
    browse(root.value).catch(() => {});
  }
});

async function run(action, data) {
  const current = epoch;
  busy.value = true;
  try {
    const res = await operation(action, data);
    taskId.value = res.data.taskId;
    while (current === epoch) {
      const result = (await operation("fileTask", { taskId: taskId.value, forget: true })).data;
      if ([2, 4, 7].includes(result.state)) {
        if (result.state === 2) ElMessage.success(t("common.success"));
        else if (result.state === 7) ElMessage.error(result.error || t("engine.cloudOperationFailed"));
        moveShow.value = false;
        await browse();
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
  } finally {
    taskId.value = null;
    busy.value = false;
  }
}

async function rename(entry) {
  try {
    const { value } = await ElMessageBox.prompt(t("engine.cloudNewName"), t("engine.cloudRename"), {
      inputValue: entry.name,
      inputValidator: value => !!value && value !== "." && value !== ".."
        && !/[\\/]/.test(value) && !Array.from(value).some(char => char.charCodeAt(0) < 32),
      inputErrorMessage: t("engine.cloudInvalidName"),
      confirmButtonText: t("common.confirm"), cancelButtonText: t("common.cancel"),
    });
    if (value !== entry.name) await run("fileRename", { path: fullPath(entry), name: value });
  } catch { /* Request errors are displayed by the shared request handler. */ }
}

function openMove(entry) {
  moveEntry.value = { ...entry, path: fullPath(entry) };
  moveTarget.value = "";
  moveShow.value = true;
}

async function loadFolders(node, resolve, reject) {
  if (node.level === 0) return resolve(roots.value);
  try {
    const res = await operation("fileList", { path: node.data.path });
    resolve((res.data || []).filter(item => item.is_dir).map(item => {
      const child = node.data.path + "/" + item.name;
      return { path: child, name: item.name, leaf: false,
        disabled: moveEntry.value?.is_dir && (child === moveEntry.value.path || child.startsWith(moveEntry.value.path + "/")) };
    }));
  } catch {
    reject();
  }
}

async function move() {
  if (!moveEntry.value || !moveTarget.value) return;
  await run("fileMove", { path: moveEntry.value.path, destination: moveTarget.value + "/" + moveEntry.value.name });
}

function cancel() {
  if (taskId.value) operation("fileCancel", { taskId: taskId.value }).catch(() => {});
}

onBeforeUnmount(() => { ++epoch; ++loadId; cancel(); });
</script>

<template>
  <el-dialog :model-value="modelValue" :title="$t('engine.cloudFiles') + '：' + (mount?.name || '')"
    width="min(960px, calc(100vw - 24px))" :close-on-click-modal="!busy" :close-on-press-escape="!busy"
    :show-close="!busy" class="cloud-files-dialog" @update:model-value="emit('update:modelValue', $event)">
    <div class="cloud-file-toolbar">
      <el-tooltip :content="$t('engine.cloudParent')">
        <el-button :icon="ArrowUp" :aria-label="$t('engine.cloudParent')" :disabled="busy || loading || path === root"
          @click="browse(path.slice(0, path.lastIndexOf('/'))).catch(() => {})" />
      </el-tooltip>
      <strong>{{ path }}</strong>
      <el-tooltip :content="$t('engine.cloudRefresh')">
        <el-button :icon="RefreshRight" :aria-label="$t('engine.cloudRefresh')" :disabled="busy" :loading="loading"
          @click="browse().catch(() => {})" />
      </el-tooltip>
    </div>
    <el-table v-loading="loading" :data="entries" height="380" row-key="name">
      <el-table-column :label="$t('taskDetail.fileName')" min-width="200">
        <template #default="{ row }">
          <el-button v-if="row.is_dir" link :icon="Folder" :disabled="busy || loading" @click="browse(fullPath(row)).catch(() => {})">{{ row.name }}</el-button>
          <span v-else class="cloud-file-name"><el-icon><Document /></el-icon>{{ row.name }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="$t('engine.cloudSize')" width="105"><template #default="{ row }">{{ parseSize(row.size) }}</template></el-table-column>
      <el-table-column :label="$t('engine.cloudCreated')" width="180"><template #default="{ row }">{{ timestamp(row.created_at) }}</template></el-table-column>
      <el-table-column :label="$t('engine.cloudModified')" width="180"><template #default="{ row }">{{ timestamp(row.modified_at) }}</template></el-table-column>
      <el-table-column width="104" fixed="right" :label="$t('common.operate')">
        <template #default="{ row }">
          <div class="cloud-file-actions">
            <el-tooltip :content="$t('engine.cloudRename')"><el-button :icon="Edit" :aria-label="$t('engine.cloudRename')" :disabled="busy || loading" @click="rename(row)" /></el-tooltip>
            <el-tooltip :content="$t('engine.cloudMove')"><el-button :icon="Right" :aria-label="$t('engine.cloudMove')" :disabled="busy || loading" @click="openMove(row)" /></el-tooltip>
          </div>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button v-if="busy" :icon="Close" :disabled="!taskId" @click="cancel">{{ $t('common.cancel') }}</el-button>
    </template>
  </el-dialog>
  <el-dialog v-model="moveShow" :title="$t('engine.cloudMove')" width="min(480px, calc(100vw - 24px))"
    :show-close="!busy" :close-on-click-modal="!busy" :close-on-press-escape="!busy">
    <el-form label-position="top">
      <el-form-item :label="$t('engine.cloudDestination')">
        <el-tree-select v-model="moveTarget" :key="moveEntry?.path" :data="roots" node-key="path" lazy :load="loadFolders"
          :props="{ label: 'name', value: 'path', isLeaf: 'leaf', disabled: 'disabled' }" :disabled="busy"
          check-strictly :render-after-expand="false" :placeholder="$t('pathSelect.title')" style="width: 100%" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :disabled="busy && !taskId" @click="busy ? cancel() : (moveShow = false)">{{ $t('common.cancel') }}</el-button>
      <el-button type="primary" :icon="FolderOpened" :loading="busy" :disabled="!moveTarget || moveTarget === path"
        @click="move().catch(() => {})">{{ $t('common.confirm') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.cloud-file-toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.cloud-file-toolbar strong { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.cloud-file-name { display: inline-flex; align-items: center; gap: 6px; overflow-wrap: anywhere; }
.cloud-file-actions { display: flex; gap: 6px; }
.cloud-file-actions .el-button { width: 32px; height: 32px; padding: 0; flex: 0 0 32px; }
:global(.cloud-files-dialog .el-dialog__title) { display: inline-block; max-width: calc(100% - 32px); overflow-wrap: anywhere; }
:deep(.el-table .el-button) { margin: 0; padding: 8px; }
:deep(.el-table .el-button.is-link) { white-space: normal; text-align: left; word-break: break-word; }
</style>
