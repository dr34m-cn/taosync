<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import { Check, Delete, Lock, Refresh, UploadFilled } from '@element-plus/icons-vue';
import { useI18n } from 'vue-i18n';
import { applyHttps, clearHttpsCertificate, getHttpsStatus } from '@/api/settings';

const { t } = useI18n();
const status = ref(null);
const enabled = ref(false);
const pending = ref('');
const busy = computed(() => !!pending.value);
const maxPemBytes = 256 * 1024;
const fields = ref(newFields());
const modes = computed(() => [
  { value: 'file', label: t('https.uploadFile') },
  { value: 'text', label: t('https.enterText') },
]);
const plainHttp = window.location.protocol === 'http:';
const address = computed(() => 'https://' + window.location.hostname + ':' + status.value?.port + '/');
const inputs = computed(() => fields.value.map(field => {
  const value = field.mode === 'file' ? field.files[0]?.raw : field.text;
  const invalid = typeof value === 'string'
    ? value !== '' && (!value.trim() || new Blob([value]).size > maxPemBytes)
    : value && (!value.size || value.size > maxPemBytes);
  return { field, value, invalid };
}));
const canApply = computed(() => {
  if (!enabled.value) return status.value?.autoStart;
  if (inputs.value.every(({ value, invalid }) => value && !invalid)) return true;
  return status.value?.configured && !status.value.enabled && inputs.value.every(({ value }) => !value);
});

function newFields() {
  return [
    { name: 'certificate', accept: '.cer,.crt,.pem' },
    { name: 'privateKey', accept: '.key,.pem' },
  ].map(field => ({ ...field, mode: 'file', files: [], text: '' }));
}

function reset(data) {
  status.value = data;
  enabled.value = data.autoStart;
  fields.value = newFields();
}

async function load() {
  pending.value = 'load';
  try { reset((await getHttpsStatus()).data); } catch { /* request reports the error */ }
  finally { pending.value = ''; }
}

async function save() {
  if (busy.value || !canApply.value) return;
  pending.value = 'save';
  try {
    const data = { enabled: enabled.value };
    if (enabled.value) {
      try {
        for (const { field, value } of inputs.value) {
          if (value) data[field.name] = typeof value === 'string' ? value : await value.text();
        }
      } catch {
        ElMessage.error(t('https.readError'));
        return;
      }
    }
    reset((await applyHttps(data)).data);
    ElMessage.success(t('setting.saved'));
  } catch { /* Keep the draft when validation or binding fails. */ }
  finally { pending.value = ''; }
}

async function clearSaved() {
  if (busy.value || !status.value?.configured) return;
  pending.value = 'confirm';
  try {
    await ElMessageBox.confirm(t(status.value.enabled ? 'https.clearActiveConfirm' : 'https.clearConfirm'), t('https.clear'), {
      type: 'warning', confirmButtonText: t('https.clear'), cancelButtonText: t('common.cancel'),
      confirmButtonType: 'danger',
    });
    pending.value = 'clear';
    reset((await clearHttpsCertificate()).data);
    ElMessage.success(t('https.cleared'));
  } catch { /* Cancelling or a failed request keeps the current settings and draft. */ }
  finally { pending.value = ''; }
}

onMounted(load);
</script>

<template>
  <section aria-labelledby="https-heading" :aria-busy="busy">
    <header class="section-toolbar">
      <h2 id="https-heading" class="section-heading"><el-icon aria-hidden="true"><Lock /></el-icon>HTTPS</h2>
      <el-switch v-if="status" v-model="enabled" :aria-label="t('https.enable')" :disabled="busy" @change="fields = newFields()" />
    </header>
    <el-button v-if="!status && !busy" :icon="Refresh" @click="load">{{ t('retry') }}</el-button>
    <template v-if="status">
      <a v-if="status.enabled" :href="address" target="_blank" rel="noopener noreferrer">{{ address }}</a>
      <p v-else-if="status.configured" role="status">{{ t(status.autoStart ? 'https.inactive' : 'https.retained') }}</p>
      <form v-if="enabled || status.configured" @submit.prevent="save">
        <template v-if="enabled">
          <p>{{ t('https.files') }}</p>
          <p v-if="plainHttp" class="warning">{{ t('https.plainHttp') }}</p>
          <div class="pem-fields">
            <fieldset v-for="{ field, invalid } in inputs" :key="field.name" class="pem-field">
              <legend>{{ t(`https.${field.name}`) }}</legend>
              <el-segmented v-model="field.mode" :options="modes" size="small" :disabled="busy"
                :aria-label="t('https.inputMode', { field: t(`https.${field.name}`) })" />
              <el-upload v-if="field.mode === 'file'" drag :accept="field.accept" :auto-upload="false" :disabled="busy"
                :file-list="field.files" :on-change="file => field.files = [file]" :on-remove="() => field.files = []">
                <el-icon :size="28" class="upload-icon" aria-hidden="true"><UploadFilled /></el-icon>
                <i18n-t keypath="https.dropFile" tag="div" class="el-upload__text">
                  <template #choose><em>{{ t('https.chooseFile') }}</em></template>
                </i18n-t>
                <span class="file-hint">{{ t('https.fileHint', { formats: field.accept.replaceAll(',', ', ') }) }}</span>
              </el-upload>
              <el-input v-else v-model="field.text" type="textarea" :rows="5" resize="vertical" :disabled="busy"
                :aria-label="t(`https.${field.name}`)" :placeholder="t('https.pemPlaceholder')" :aria-invalid="!!invalid"
                :aria-describedby="invalid ? `https-${field.name}-error` : undefined"
                autocomplete="off" autocapitalize="off" :spellcheck="false" />
              <p v-if="invalid" :id="`https-${field.name}-error`" class="pem-error" role="alert">{{ t('https.contentSize') }}</p>
            </fieldset>
          </div>
        </template>
        <p v-else-if="status.autoStart">{{ t('https.disableHint') }}</p>
        <div class="https-actions">
          <el-button v-if="enabled || status.autoStart" type="primary" native-type="submit" :icon="Check" :loading="pending === 'save'" :disabled="busy || !canApply">{{ t('setting.saveAndApply') }}</el-button>
          <el-button v-if="status.configured" type="danger" plain :icon="Delete" :loading="pending === 'clear'" :disabled="busy" @click="clearSaved">{{ t('https.clear') }}</el-button>
        </div>
      </form>
    </template>
  </section>
</template>

<style scoped>
.section-toolbar:not(:last-child) { margin-bottom: 12px; }
p, a { font-size: 14px; }
a { color: var(--el-color-primary); overflow-wrap: anywhere; }
.warning { color: var(--el-color-warning-dark-2); }
.pem-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; margin: 16px 0; }
.pem-field { min-width: 0; margin: 0; padding: 0; border: 0; }
.pem-field legend { margin-bottom: 8px; padding: 0; font-size: 14px; font-weight: 600; }
.pem-field .el-segmented { margin-bottom: 10px; }
.pem-field :deep(.el-upload-dragger) { padding: 16px; border-radius: 8px; }
.pem-field :deep(.el-upload:focus-visible .el-upload-dragger) { outline: 2px solid var(--el-color-primary); }
.pem-field :deep(.el-upload-list:empty) { display: none; }
.upload-icon { color: var(--el-color-primary); }
.el-upload__text { margin: 3px 0; }
.file-hint { color: var(--text-secondary); font-size: 12px; }
.pem-field :deep(textarea) { font-family: var(--el-font-family-monospace, monospace); }
.pem-error { margin: 6px 0 0; color: var(--el-color-danger); font-size: 12px; }
.https-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.https-actions .el-button { margin: 0; }
@container (max-width: 640px) {
  .pem-fields { grid-template-columns: minmax(0, 1fr); }
}
</style>
