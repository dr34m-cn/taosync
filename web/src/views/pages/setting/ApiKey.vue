<script setup>
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessageBox } from 'element-plus';
import { CopyDocument, Key, QuestionFilled, Refresh } from '@element-plus/icons-vue';
import { useClipboard } from '@vueuse/core';
import { marked } from 'marked';
import { changeApiKey, getApiKeyStatus } from '@/api/settings';
import guideZh from './api-key.md?raw';
import guideEn from './api-key.en.md?raw';

const help = ref(false);
const { t, locale } = useI18n();
const guideHtml = computed(() => marked.parse(locale.value === 'en' ? guideEn : guideZh));
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
      const resetting = action === 'reset';
      const confirmed = await ElMessageBox.confirm(t('apiKey.confirmHint'), t(resetting ? 'apiKey.resetTitle' : 'apiKey.disableTitle'), {
        confirmButtonText: t(resetting ? 'apiKey.reset' : 'common.disable'), cancelButtonText: t('common.cancel'), type: 'warning',
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
    <header class="section-toolbar key-heading">
      <h2 id="api-key-title" class="section-heading"><el-icon aria-hidden="true"><Key /></el-icon>{{ t('apiKey.title') }}</h2>
      <el-button class="guide-action" link type="primary" :icon="QuestionFilled" :aria-label="t('apiKey.help')" :title="t('apiKey.help')" @click="help = true">{{ t('apiKey.help') }}</el-button>
      <div v-if="enabled !== null" class="controls">
        <el-switch :model-value="enabled" :disabled="busy" :aria-label="t('apiKey.enable')" @change="change($event ? 'enable' : 'disable')" />
        <span>{{ t(enabled ? 'notify.enabled' : 'notify.disabled') }}</span>
        <el-button v-if="enabled" class="reset-action" size="small" :icon="Refresh" :disabled="busy" :aria-label="t('apiKey.reset')" :title="t('apiKey.reset')" @click="change('reset')">{{ t('apiKey.reset') }}</el-button>
      </div>
      <el-button v-else-if="!busy" size="small" :icon="Refresh" @click="load">{{ t('apiKey.reload') }}</el-button>
    </header>
    <el-dialog :model-value="!!key" :title="t('apiKey.newKey')" width="min(540px, 92vw)" append-to-body destroy-on-close
      :close-on-click-modal="false" @close="key = ''">
      <p class="key-notice">{{ t('apiKey.notice') }}</p>
      <code class="issued-key">{{ key }}</code>
      <template #footer>
        <el-button :icon="CopyDocument" @click="copy(key)">{{ t(copied ? 'apiKey.copied' : 'apiKey.copy') }}</el-button>
        <el-button type="primary" @click="key = ''">{{ t('apiKey.close') }}</el-button>
      </template>
    </el-dialog>
    <el-dialog v-model="help" :title="t('apiKey.helpTitle')" width="min(640px, 92vw)" append-to-body>
      <article class="key-guide" v-html="guideHtml" />
    </el-dialog>
  </section>
</template>

<style scoped>
.key-heading { white-space: nowrap; }
.controls { display: flex; align-items: center; gap: var(--toolbar-gap, 12px); margin-inline-start: auto; font-size: 14px; }
.key-notice { margin: 0 0 12px; line-height: 1.6; }
.issued-key { display: block; overflow-wrap: anywhere; user-select: all; }
@container (max-width: 440px) {
  .key-heading { --toolbar-gap: 6px; }
  .key-heading .section-heading { gap: 4px; }
  .key-heading .section-heading > .el-icon { display: none; }
}
@container (max-width: 400px) {
  .reset-action { width: 28px; height: 28px; padding: 0; }
  .reset-action > :deep(span) { display: none; }
}
@container (max-width: 340px) {
  .guide-action { width: 28px; height: 28px; }
  .guide-action > :deep(span) { display: none; }
}
.key-guide { line-height: 1.65; }
.key-guide :deep(h3:first-child) { margin-top: 0; }
.key-guide :deep(pre) { padding: 12px; overflow-x: auto; background: var(--el-fill-color-light); border-radius: 6px; }
</style>
