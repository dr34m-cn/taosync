<script setup>
import { computed, onMounted, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { Check, Lock, Refresh } from '@element-plus/icons-vue';
import { useI18n } from 'vue-i18n';
import { applyHttps, getHttpsStatus } from '@/api/settings';

const { t } = useI18n();
const status = ref(null);
const enabled = ref(false);
const busy = ref(false);
const certificate = ref(null);
const privateKey = ref(null);
const revision = ref(0);
const plainHttp = window.location.protocol === 'http:';
const address = computed(() => 'https://' + window.location.hostname + ':' + status.value?.port + '/');
const canApply = computed(() => enabled.value
  ? (certificate.value && privateKey.value) || (status.value?.configured && !status.value.enabled && !certificate.value && !privateKey.value)
  : status.value?.configured);

function reset(data) {
  status.value = data;
  enabled.value = data.configured;
  certificate.value = privateKey.value = null;
  revision.value++;
}

async function load() {
  busy.value = true;
  try { reset((await getHttpsStatus()).data); } catch { /* request reports the error */ }
  finally { busy.value = false; }
}

async function save() {
  if (busy.value || !canApply.value) return;
  busy.value = true;
  try {
    const data = { enabled: enabled.value };
    if (enabled.value && certificate.value) {
      if ([certificate.value, privateKey.value].some(file => file.size > 256 * 1024 || !file.size)) {
        ElMessage.error(t('https.fileSize'));
        return;
      }
      try {
        [data.certificate, data.privateKey] = await Promise.all([certificate.value.text(), privateKey.value.text()]);
      } catch {
        ElMessage.error(t('https.readError'));
        return;
      }
    }
    reset((await applyHttps(data)).data);
    ElMessage.success(t('setting.saved'));
  } catch { /* Keep the draft when validation or binding fails. */ }
  finally { busy.value = false; }
}

onMounted(load);
</script>

<template>
  <section aria-labelledby="https-heading" :aria-busy="busy">
    <header class="https-heading">
      <h2 id="https-heading" class="section-heading"><el-icon aria-hidden="true"><Lock /></el-icon>HTTPS</h2>
      <el-switch v-if="status" v-model="enabled" :aria-label="t('https.enable')" :disabled="busy" @change="certificate = privateKey = null" />
    </header>
    <el-button v-if="!status && !busy" :icon="Refresh" @click="load">{{ t('retry') }}</el-button>
    <template v-if="status">
      <a v-if="status.enabled" :href="address" target="_blank" rel="noopener noreferrer">{{ address }}</a>
      <p v-else-if="status.configured" role="status">{{ t('https.inactive') }}</p>
      <form v-if="enabled || status.configured" @submit.prevent="save">
        <template v-if="enabled">
          <p>{{ t('https.files') }}</p>
          <p v-if="plainHttp" class="warning">{{ t('https.plainHttp') }}</p>
          <div :key="revision" class="https-files">
            <label>{{ t('https.certificate') }}<input type="file" accept=".cer,.crt,.pem" :disabled="busy" @change="certificate = $event.target.files[0]" /></label>
            <label>{{ t('https.privateKey') }}<input type="file" accept=".key,.pem" :disabled="busy" @change="privateKey = $event.target.files[0]" /></label>
          </div>
        </template>
        <p v-else>{{ t('https.disableHint') }}</p>
        <el-button type="primary" native-type="submit" :icon="Check" :loading="busy" :disabled="!canApply">{{ t('setting.saveAndApply') }}</el-button>
      </form>
    </template>
  </section>
</template>

<style scoped>
.https-heading, .https-files { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 24px; }
.https-heading .section-heading { margin: 0; }
p, a, label { font-size: 14px; }
a { color: var(--el-color-primary); overflow-wrap: anywhere; }
.warning { color: var(--el-color-warning-dark-2); }
.https-files { margin-bottom: 16px; }
label, input { display: block; max-width: 100%; }
input { margin-top: 6px; }
</style>
