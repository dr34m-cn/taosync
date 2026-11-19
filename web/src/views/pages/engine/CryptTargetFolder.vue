<script setup>
import { alistGetPath } from "@/api/job";

const props = defineProps({ engineId: Number, mount: Object });
const path = defineModel({ type: String });
const root = { path: "/" };

async function loadFolders(node, resolve, reject) {
  if (node.level === 0) return resolve([root]);
  const mount = props.mount;
  if (!mount) return reject();
  const parent = node.data.path === "/" ? "" : node.data.path;
  try {
    const res = await alistGetPath(props.engineId, `/${mount.name}${parent}/`);
    if (mount !== props.mount) return reject();
    const children = (res.data || []).filter(({ path: name }) =>
      typeof name === "string" && name && name !== "." && name !== ".." && !/[/\\]/.test(name));
    resolve(children.map(({ path: name }) => ({ path: `${parent}/${name}` })));
  } catch {
    reject();
  }
}
</script>

<template>
  <el-tree-select v-model="path" node-key="path" :props="{ label: 'path', value: 'path' }"
    :disabled="!mount" :cache-data="[root]" :load="loadFolders" lazy check-strictly
    :render-after-expand="false" :placeholder="$t('engine.cryptFolder')" />
</template>
