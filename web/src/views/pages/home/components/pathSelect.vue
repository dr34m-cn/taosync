<script setup>
import { ref } from "vue";
import { alistGetPath } from "@/api/job";
import { useI18n } from "vue-i18n";

const props = defineProps({
  alistId: {
    type: Number,
    default: null,
  },
});
const emit = defineEmits(["submit"]);
const { t } = useI18n();
const dialogShow = ref(false);
const pathLoading = ref(false);
const cuPath = ref(null);
const treeProps = {
  label: "path",
  children: "child",
  isLeaf: "leaf",
};

const show = () => {
  dialogShow.value = true;
};

const getPath = async (path) => {
  pathLoading.value = true;
  try {
    const res = await alistGetPath(props.alistId, path);
    return res.data;
  } catch (err) {
    return [];
  } finally {
    pathLoading.value = false;
  }
};

const buildPath = (node) => {
  let path = "/";
  let cup = node;
  for (let i = 0; i < node.level; i++) {
    path = "/" + cup.data.path + path;
    cup = cup.parent;
  }
  return path;
};

const loadNode = async (node, resolve) => {
  resolve(await getPath(buildPath(node)));
};

const closeShow = () => {
  dialogShow.value = false;
  cuPath.value = null;
};

const nodeClick = (dt, node) => {
  cuPath.value = buildPath(node);
};

const submit = () => {
  emit("submit", cuPath.value);
  closeShow();
};

defineExpose({
  show,
});
</script>

<template>
  <el-dialog top="8vh" :close-on-click-modal="false" v-model="dialogShow" :title="$t('pathSelect.title')" width="520px" :append-to-body="true">
    <el-tree
      v-loading="pathLoading"
      :props="treeProps"
      :load="loadNode"
      lazy
      highlight-current
      check-on-click-node
      @node-click="nodeClick"
      v-if="dialogShow"
    />
    <template #footer>
      <el-button @click="closeShow">{{ t("common.cancel") }}</el-button>
      <el-button type="primary" @click="submit" :disabled="cuPath == null">
        {{ cuPath == null ? t("pathSelect.selectFirst") : t("common.confirm") }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style lang="scss" scoped>
@media (max-width: 768px) {
  :deep(.el-tree) {
    overflow-x: auto;
  }

  :deep(.el-tree-node__content) {
    min-width: max-content;
  }
}
</style>
