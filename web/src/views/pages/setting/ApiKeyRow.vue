<script setup>
import { onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessageBox } from 'element-plus';
import { CopyDocument, Refresh } from '@element-plus/icons-vue';
import { useClipboard } from '@vueuse/core';
import { changeApiKey, getApiKeyStatus } from '@/api/settings';

const props = defineProps({ scope: { type: String, default: 'general' } });
const titleId = `api-key-${props.scope}`;
const { t } = useI18n();
const enabled = ref(null);
const busy = ref(false);
const key = ref('');
const { copy, copied } = useClipboard({ source: key, legacy: true });

async function load() {
  busy.value = true;
  try {
    enabled.value = (await getApiKeyStatus(props.scope)).data.enabled;
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
    const { data } = await changeApiKey(action, props.scope);
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
  <div class="key-row" :aria-busy="busy">
    <header class="section-toolbar key-heading">
      <strong :id="titleId">{{ t(scope === 'execute' ? 'apiKey.executeTitle' : 'apiKey.title') }}</strong>
      <div v-if="enabled !== null" class="controls">
        <el-switch :model-value="enabled" :disabled="busy" :aria-labelledby="titleId" @change="change($event ? 'enable' : 'disable')" />
        <span>{{ t(enabled ? 'notify.enabled' : 'notify.disabled') }}</span>
        <el-button v-if="enabled" class="reset-action" size="small" :icon="Refresh" :disabled="busy" :aria-label="t('apiKey.reset')" :title="t('apiKey.reset')" @click="change('reset')">{{ t('apiKey.reset') }}</el-button>
      </div>
      <el-button v-else-if="!busy" size="small" :icon="Refresh" @click="load">{{ t('apiKey.reload') }}</el-button>
    </header>
    <el-dialog :model-value="!!key" :title="t('apiKey.newKey')" width="min(540px, 92vw)" append-to-body destroy-on-close
      :close-on-click-modal="false" @close="key = ''">
      <el-alert :title="t('apiKey.warning')" type="error" show-icon :closable="false" />
      <p class="key-notice">{{ t('apiKey.notice') }}</p>
      <code class="issued-key">{{ key }}</code>
      <template #footer>
        <el-button :icon="CopyDocument" @click="copy(key)">{{ t(copied ? 'apiKey.copied' : 'apiKey.copy') }}</el-button>
        <el-button type="primary" @click="key = ''">{{ t('apiKey.close') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.key-row { padding: 12px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.key-row:last-child { border-bottom: 0; padding-bottom: 0; }
.key-heading { flex-wrap: wrap; }
.controls { display: flex; align-items: center; gap: var(--toolbar-gap, 12px); margin-inline-start: auto; font-size: 14px; }
.key-notice { margin: 0 0 12px; line-height: 1.6; }
.issued-key { display: block; overflow-wrap: anywhere; user-select: all; }
@container (max-width: 400px) {
  .reset-action { width: 28px; height: 28px; padding: 0; }
  .reset-action > :deep(span) { display: none; }
}
</style>
