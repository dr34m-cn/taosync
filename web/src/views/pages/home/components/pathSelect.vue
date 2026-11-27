<script setup>
import { nextTick, ref, watch } from "vue";
import { FolderAdd } from "@element-plus/icons-vue";
import { alistCreateDirectory, alistGetPath } from "@/api/job";
import { useI18n } from "vue-i18n";

const props = defineProps({
  alistId: Number,
  // A physical root is selectable and writable; the virtual job root is neither.
  physicalRoot: Boolean,
  rootNode: Object,
  listFolders: Function,
  makeFolder: Function,
});
const emit = defineEmits(["submit"]);
const { t } = useI18n();
const dialogShow = ref(false);
const treeKey = ref(0);
const tree = ref();
const selected = ref(null);
const createShow = ref(false);
const folderInput = ref();
const folderName = ref("");
const parentNode = ref(null);
const saving = ref(false);
const nameError = ref("");

watch(
  () => [props.rootNode?.path, props.rootNode?.label, props.rootNode?.id],
  () => {
    if (!dialogShow.value) return;
    selected.value = null;
    createShow.value = false;
    parentNode.value = null;
    treeKey.value += 1;
  }
);

function show() {
  selected.value = null;
  dialogShow.value = true;
}

async function loadNode(node, resolve, reject) {
  if (node.level === 0) {
    resolve([props.rootNode || { label: t("engine.rootPath"), path: "/", id: "root" }]);
    return;
  }
  const path = node.data.path;
  try {
    if (props.listFolders) return resolve(await props.listFolders(node.data));
    const { data } = await alistGetPath(props.alistId, path);
    const children = data.map(item => ({ label: item.path, path: `${path}${item.path}/` }));
    resolve(children);
  } catch {
    reject();
  }
}

function openCreate(node) {
  parentNode.value = node;
  folderName.value = "";
  nameError.value = "";
  node.expand();
  createShow.value = true;
}

async function createFolder() {
  const parent = parentNode.value;
  if (saving.value || !parent || parent.loading) return;
  const name = folderName.value.trim();
  if (!name || name === "." || name === ".." || /[/\\]/.test(name) || [...name].some(char => char.charCodeAt(0) < 32)) {
    nameError.value = t("pathSelect.invalidName");
    return;
  }
  // Retry a failed lazy load before appending so existing siblings remain visible.
  if (!parent.loaded) {
    parent.expand(() => {
      if (createShow.value && parentNode.value === parent && folderName.value.trim() === name) createFolder();
    });
    return;
  }
  saving.value = true;
  try {
    const directory = props.makeFolder ? await props.makeFolder(parent.data, name)
      : { label: name, path: (await alistCreateDirectory(props.alistId, parent.data.path, name)).data };
    if (!tree.value) return;
    const { path } = directory;
    if (!tree.value.getNode(path)) tree.value.append(directory, parent.data);
    parent.expand(null, true);
    tree.value.setCurrentKey(path);
    selected.value = directory;
    createShow.value = false;
    await nextTick();
    tree.value.$el.querySelector(".is-current > .el-tree-node__content")?.scrollIntoView({ block: "nearest" });
  } catch {
    // The request interceptor displays the server error. Keep the name for retry.
  } finally {
    saving.value = false;
  }
}

function submit() {
  emit("submit", selected.value.path, selected.value);
  dialogShow.value = false;
}

defineExpose({ show });
</script>

<template>
  <el-dialog v-model="dialogShow" top="8vh" :close-on-click-modal="false" :title="t('pathSelect.title')" width="min(520px, 94vw)" append-to-body>
    <slot name="toolbar" />
    <el-tree v-if="dialogShow" :key="treeKey" ref="tree" node-key="path" :load="loadNode" lazy highlight-current
      :default-expanded-keys="['/']" @node-click="data => selected = physicalRoot || data.path !== '/' ? data : null">
      <template #default="{ node, data }">
        <span class="directory-row">
          <span class="directory-label" :title="data.title || data.path">{{ data.label }}</span>
          <el-button v-if="physicalRoot || data.path !== '/'" link type="primary" :icon="FolderAdd" :title="t('pathSelect.newFolder')" :aria-label="t('pathSelect.newFolder')"
            :disabled="node.loading" @click.stop="openCreate(node)" />
        </span>
      </template>
    </el-tree>
    <template #footer>
      <el-button @click="dialogShow = false">{{ t("common.cancel") }}</el-button>
      <el-button type="primary" :disabled="!selected" @click="submit">{{ selected ? t("common.confirm") : t("pathSelect.selectFirst") }}</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="createShow" append-to-body :title="t('pathSelect.newFolder')" width="min(400px, 92vw)"
    :close-on-click-modal="false" :close-on-press-escape="!saving" :show-close="!saving" @opened="folderInput?.focus()">
    <el-form label-position="top" @submit.prevent="createFolder">
      <el-form-item :label="t('pathSelect.name')" :error="nameError">
        <el-input ref="folderInput" v-model="folderName" :disabled="saving" @input="nameError = ''" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button :disabled="saving" @click="createShow = false">{{ t('common.cancel') }}</el-button>
      <el-button type="primary" :loading="saving" :disabled="!parentNode || parentNode.loading" @click="createFolder">{{ t('common.confirm') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.directory-row {
  display: flex;
  align-items: center;
  flex: 1;
  min-width: 0;
  gap: 8px;
  padding-right: 6px;
}
.directory-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
