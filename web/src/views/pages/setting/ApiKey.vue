<script setup>
import { onMounted, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import { CopyDocument, Key, QuestionFilled, Refresh } from '@element-plus/icons-vue';
import { useClipboard } from '@vueuse/core';
import { marked } from 'marked';
import { changeApiKey, getApiKeyStatus } from '@/api/settings';
import guide from './api-key.md?raw';

const help = ref(false);
const guideHtml = marked.parse(guide); // Only the bundled Markdown file is rendered.
const enabled = ref(null);
const busy = ref(false);
const key = ref('');
const { copy, copied } = useClipboard({ source: key, legacy: true });

async function load() {
  busy.value = true;
  try {
    enabled.value = (await getApiKeyStatus()).data.enabled;
  } catch {
    enabled.value = null;
  } finally {
    busy.value = false;
  }
}

async function change(action) {
  if (busy.value) return;
  busy.value = true;
  try {
    if (action !== 'enable') {
      const verb = action === 'reset' ? '重置' : '禁用';
      const confirmed = await ElMessageBox.confirm(`${verb}后，使用当前密钥的脚本将无法调用接口。`, `${verb} API 密钥？`, {
        confirmButtonText: verb, cancelButtonText: '取消', type: 'warning',
      }).then(() => true, () => false);
      if (!confirmed) return;
    }
    const { data } = await changeApiKey(action);
    enabled.value = data.enabled;
    key.value = data.key || '';
  } catch {
    key.value = '';
    await load(); // The server may have committed before the connection failed.
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section aria-labelledby="api-key-title" :aria-busy="busy">
    <header class="key-heading">
      <h2 id="api-key-title" class="section-heading"><el-icon><Key /></el-icon>API 密钥</h2>
      <el-button link type="primary" :icon="QuestionFilled" @click="help = true">使用说明</el-button>
    </header>
    <div v-if="enabled !== null" class="controls">
      <el-switch :model-value="enabled" :disabled="busy" aria-label="启用 API 密钥" @change="change($event ? 'enable' : 'disable')" />
      <span>{{ enabled ? '已启用' : '已禁用' }}</span>
      <el-button v-if="enabled" :icon="Refresh" :disabled="busy" @click="change('reset')">重置密钥</el-button>
    </div>
    <el-button v-else-if="!busy" :icon="Refresh" @click="load">重新加载密钥状态</el-button>
    <template v-if="key">
      <p>新密钥仅在本次显示，请立即复制并妥善保管。</p>
      <el-input :model-value="key" readonly aria-label="新 API 密钥" @focus="$event.target.select()">
        <template #append><el-button :icon="CopyDocument" @click="copy(key)">{{ copied ? '已复制' : '复制' }}</el-button></template>
      </el-input>
    </template>
    <el-dialog v-model="help" title="API 密钥使用说明" width="min(640px, 92vw)" append-to-body>
      <article class="key-guide" v-html="guideHtml" />
    </el-dialog>
  </section>
</template>

<style scoped>
.key-heading, .controls { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.key-heading { margin-bottom: 16px; }
.key-heading .section-heading { margin-bottom: 0; }
.controls, p { font-size: 14px; }
.key-guide { line-height: 1.65; }
.key-guide :deep(h3:first-child) { margin-top: 0; }
.key-guide :deep(pre) { padding: 12px; overflow-x: auto; background: var(--el-fill-color-light); border-radius: 6px; }
</style>
