<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { ElMessageBox } from 'element-plus';
import { Close, Download, Refresh, Upload, UploadFilled, Warning } from '@element-plus/icons-vue';
import axios from 'axios';
import { useI18n } from 'vue-i18n';
import {
  AUTO_SOURCE_OPTION,
  LATEST_STABLE_OPTION,
  buildSourceOptions,
  buildVersionOptions,
  formatByteSize,
  formatSourceLabel,
  reconcileSelectedSource,
  resolveSelectedVersionEntry,
} from '@/utils/programUpdate';

const { t, locale } = useI18n();
const endpoint = '/svr/settings/update';
const info = ref(null);
const releases = ref(null);
const releasesLoading = ref(false);
const releasesError = ref('');
const selectedVersion = ref(LATEST_STABLE_OPTION);
const selectedSource = ref(AUTO_SOURCE_OPTION);
const onlineState = ref(null);
const cancelingOnline = ref(false);

const files = ref([]);
const file = computed(() => files.value[0]?.raw);
const phase = ref('loading');
const message = ref('');
const progress = ref(0);
const controller = new AbortController();
const receiptKey = 'taosync-program-update';
const signal = controller.signal;
let refreshTimer;

const versionOptions = computed(() => buildVersionOptions(releases.value));
const selectedVersionEntry = computed(() => resolveSelectedVersionEntry(releases.value, selectedVersion.value));
const isDevSelected = computed(() => selectedVersionEntry.value?.channel === 'dev');
const sourceOptions = computed(() => buildSourceOptions(releases.value, selectedVersion.value));
const onlineBusy = computed(() => ['probing', 'downloading', 'verifying', 'restarting'].includes(onlineState.value?.phase));
const onlineCanCancel = computed(() => ['probing', 'downloading'].includes(onlineState.value?.phase));
const busy = computed(() => ['confirm', 'upload', 'restart'].includes(phase.value) || onlineBusy.value);
const canStartOnline = computed(() => {
  if (busy.value || phase.value === 'unknown' || releasesLoading.value) return false;
  return Boolean(selectedVersionEntry.value && selectedVersionEntry.value.sources?.length);
});

const onlineProgressPercent = computed(() => {
  const current = onlineState.value;
  if (!current) return 0;
  if (current.phase === 'verifying' || current.phase === 'restarting') return 100;
  if (current.phase === 'downloading' && current.totalBytes > 0) {
    return Math.min(100, Math.round((100 * current.downloadedBytes) / current.totalBytes));
  }
  return 0;
});

const onlineIndeterminate = computed(() => {
  const current = onlineState.value;
  if (!current) return false;
  return current.phase === 'probing' || (current.phase === 'downloading' && !current.totalBytes);
});

const onlineStatusText = computed(() => {
  const current = onlineState.value;
  if (!current) return '';
  if (current.phase === 'probing') return t('programUpdate.probing');
  if (current.phase === 'downloading') {
    const sourceName = formatSourceLabel(current.source, locale.value) || current.source?.id || '';
    const loaded = formatByteSize(current.downloadedBytes || 0);
    if (current.totalBytes > 0) {
      return t('programUpdate.downloadingTotal', {
        source: sourceName,
        loaded,
        total: formatByteSize(current.totalBytes),
      });
    }
    return t('programUpdate.downloading', { source: sourceName, loaded });
  }
  if (current.phase === 'verifying') return t('programUpdate.verifying');
  if (current.phase === 'restarting') return t('programUpdate.restarting');
  return current.message || '';
});

watch([releases, selectedVersion], () => {
  if (releases.value) {
    const validVersions = new Set(versionOptions.value.map(item => item.value));
    if (!validVersions.has(selectedVersion.value)) {
      selectedVersion.value = LATEST_STABLE_OPTION;
    }
  }
  selectedSource.value = reconcileSelectedSource(releases.value, selectedVersion.value, selectedSource.value);
});

function reloadFrontend(id) {
  const url = new URL(window.location.href);
  url.searchParams.set('tao-update', id);
  // Change the document URL (before the hash route), not just the Vue route.
  window.location.replace(url.href);
}

async function status() {
  // Restart polling is deliberately quiet: a closed socket is expected here.
  const { data } = await axios.get(endpoint, { signal, timeout: 3500 });
  if (data.code !== 200) throw new Error(data.msg || t('programUpdate.readError'));
  return data.data;
}

async function fetchOnlineState() {
  const { data } = await axios.get(endpoint + '/online', {
    signal,
    timeout: 5000,
    headers: { 'Accept-Language': locale.value },
  });
  if (data.code !== 200) throw new Error(data.msg || t('programUpdate.readError'));
  return data.data;
}

async function loadReleases() {
  if (!info.value?.supported || releasesLoading.value) return;
  releasesLoading.value = true;
  releasesError.value = '';
  try {
    const { data } = await axios.get(endpoint + '/releases', {
      signal,
      timeout: 25000,
      headers: { 'Accept-Language': locale.value },
    });
    if (data.code !== 200) throw new Error(data.msg || t('programUpdate.releasesError'));
    releases.value = data.data;
  } catch (error) {
    if (!signal.aborted) {
      releasesError.value = error.response?.data?.msg || error.message || t('programUpdate.releasesError');
    }
  } finally {
    releasesLoading.value = false;
  }
}

async function waitForStart(id) {
  phase.value = 'restart';
  message.value = t('programUpdate.restarting');
  onlineState.value = null;
  const deadline = Date.now() + 180000;
  while (!signal.aborted && Date.now() < deadline) {
    try {
      info.value = await status();
      const result = info.value.result;
      if (result?.id === id && ['started', 'rollback'].includes(result.status)) {
        sessionStorage.removeItem(receiptKey);
        phase.value = result.status;
        message.value = t(result.status === 'started' ? 'programUpdate.started' : 'programUpdate.rollback');
        files.value = [];
        if (result.status === 'started') refreshTimer = setTimeout(() => reloadFrontend(id), 1000);
        return;
      }
    } catch { /* Service may be between processes. */ }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  if (!signal.aborted) {
    phase.value = 'unknown';
    message.value = t('programUpdate.unknown');
  }
}

async function pollOnlineUpdate(activeId) {
  let lastPhase = onlineState.value?.phase || 'probing';
  while (!signal.aborted) {
    try {
      const current = await fetchOnlineState();
      onlineState.value = current;
      lastPhase = current.phase;
      if (current.phase === 'restarting') {
        const receiptId = current.id || activeId;
        if (receiptId) {
          sessionStorage.setItem(receiptKey, receiptId);
          await waitForStart(receiptId);
        }
        return;
      }
      if (current.phase === 'error') {
        phase.value = 'error';
        message.value = current.message || t('programUpdate.onlineFailed');
        return;
      }
      if (current.phase === 'cancelled' || current.phase === 'idle') {
        phase.value = 'idle';
        message.value = current.message || '';
        return;
      }
    } catch (error) {
      if (signal.aborted) return;
      if (['verifying', 'restarting'].includes(lastPhase) && activeId) {
        sessionStorage.setItem(receiptKey, activeId);
        await waitForStart(activeId);
        return;
      }
      phase.value = 'error';
      message.value = error.response?.data?.msg || error.message;
      onlineState.value = null;
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 600));
  }
}

async function load() {
  const id = sessionStorage.getItem(receiptKey);
  if (id) return waitForStart(id);
  phase.value = 'loading';
  try {
    info.value = await status();
    phase.value = 'idle';
    const url = new URL(window.location.href);
    const refreshed = url.searchParams.get('tao-update');
    message.value = refreshed && refreshed === info.value.result?.id && info.value.result.status === 'started'
      ? t('programUpdate.complete') : '';
    if (refreshed) {
      url.searchParams.delete('tao-update');
      window.history.replaceState(window.history.state, '', url.href);
    }
    if (info.value.supported) {
      loadReleases();
      try {
        const current = await fetchOnlineState();
        if (['probing', 'downloading', 'verifying', 'restarting'].includes(current.phase)) {
          onlineState.value = current;
          if (current.phase === 'restarting' && current.id) {
            sessionStorage.setItem(receiptKey, current.id);
            await waitForStart(current.id);
          } else {
            await pollOnlineUpdate(current.id);
          }
        }
      } catch { /* Online update status is optional during initial load. */ }
    }
  } catch (error) {
    phase.value = 'error';
    message.value = error.message;
  }
}

function stopWaiting() {
  sessionStorage.removeItem(receiptKey);
  load();
}

function select(uploadFile) {
  message.value = '';
  if (!uploadFile.size || uploadFile.size > info.value.maxBytes) {
    files.value = [];
    message.value = t('programUpdate.fileSize');
  } else {
    files.value = [uploadFile];
  }
}

function sourceDisplayName(option) {
  if (option.isAutoOption) return t('programUpdate.autoSource');
  return formatSourceLabel(option, locale.value);
}

function versionDisplayName(option) {
  if (option.isLatestOption) {
    return option.version
      ? t('programUpdate.latestStableWithVersion', { version: option.version })
      : t('programUpdate.latestStable');
  }
  return option.version;
}

async function startOnlineUpdate() {
  if (!canStartOnline.value) return;
  const targetVersion = selectedVersionEntry.value?.version;
  if (!targetVersion) return;
  const chosenSourceObj = sourceOptions.value.find(item => item.value === selectedSource.value);
  const chosenSourceLabel = chosenSourceObj ? sourceDisplayName(chosenSourceObj) : t('programUpdate.autoSource');
  const confirmTarget = selectedVersion.value === LATEST_STABLE_OPTION
    ? t('programUpdate.latestStableWithVersion', { version: targetVersion })
    : targetVersion;

  phase.value = 'confirm';
  try {
    await ElMessageBox.confirm(
      t(isDevSelected.value ? 'programUpdate.onlineConfirmDev' : 'programUpdate.onlineConfirm', {
        version: confirmTarget,
        source: chosenSourceLabel,
      }),
      t('programUpdate.confirmTitle'),
      { type: 'warning', confirmButtonText: t('programUpdate.startOnline'), cancelButtonText: t('common.cancel') },
    );
  } catch {
    phase.value = 'idle';
    return;
  }

  phase.value = 'idle';
  message.value = '';
  try {
    const { data } = await axios.post(
      endpoint + '/online',
      { version: selectedVersion.value, source: selectedSource.value },
      {
        signal,
        timeout: 30000,
        headers: { 'X-TaoSync-Update': '1', 'Accept-Language': locale.value },
      },
    );
    if (data.code !== 200 || !data.data?.id) {
      throw new Error(data.msg || t('programUpdate.noReceipt'));
    }
    onlineState.value = data.data;
    await pollOnlineUpdate(data.data.id);
  } catch (error) {
    if (!signal.aborted) {
      phase.value = 'error';
      message.value = error.response?.data?.msg || error.message;
      onlineState.value = null;
    }
  }
}

async function cancelOnlineUpdate() {
  if (!onlineCanCancel.value || cancelingOnline.value) return;
  cancelingOnline.value = true;
  try {
    await axios.delete(endpoint + '/online', {
      signal,
      timeout: 10000,
      headers: { 'X-TaoSync-Update': '1', 'Accept-Language': locale.value },
    });
  } catch { /* Poll loop will observe final state. */ } finally {
    cancelingOnline.value = false;
  }
}

async function install() {
  if (busy.value || !file.value) return;
  phase.value = 'confirm';
  try {
    await ElMessageBox.confirm(t('programUpdate.confirm', { name: file.value.name }), t('programUpdate.confirmTitle'),
      { type: 'warning', confirmButtonText: t('programUpdate.install'), cancelButtonText: t('common.cancel') });
  } catch { phase.value = 'idle'; return; }
  progress.value = 0;
  phase.value = 'upload';
  message.value = '';
  onlineState.value = null;
  try {
    const { data } = await axios.post(endpoint + '/upload', file.value, {
      signal, timeout: 600000,
      headers: { 'Content-Type': 'application/octet-stream', 'X-TaoSync-Update': '1', 'Accept-Language': locale.value },
      onUploadProgress: event => { progress.value = Math.round(100 * event.loaded / file.value.size); },
    });
    if (!data.data?.id) throw new Error(data.msg || t('programUpdate.noReceipt'));
    sessionStorage.setItem(receiptKey, data.data.id);
    await waitForStart(data.data.id);
  } catch (error) {
    phase.value = 'error';
    message.value = error.response?.data?.msg || error.message;
  }
}

onMounted(load);
onBeforeUnmount(() => { clearTimeout(refreshTimer); controller.abort(); });
</script>

<template>
  <section class="program-update" aria-labelledby="program-update-title" :aria-busy="busy">
    <h2 id="program-update-title" class="section-heading"><el-icon aria-hidden="true"><Upload /></el-icon>{{ t('programUpdate.title') }}</h2>
    <p v-if="phase === 'loading'">{{ t('programUpdate.loading') }}</p>
    <div v-if="info" class="update-body">
      <div class="deployment">
        <dl class="platform-info">
          <div class="platform-item"><dt>{{ t('programUpdate.target') }}</dt><dd><code>{{ info.target }}</code></dd></div>
          <div class="platform-item"><dt>{{ t('programUpdate.arch') }}</dt><dd><code>{{ info.architecture || '—' }}</code></dd></div>
          <div class="platform-item"><dt>{{ t('programUpdate.currentVersion') }}</dt><dd><code>{{ info.version || '—' }}</code></dd></div>
        </dl>
        <el-alert
          v-if="info.supported && info.container"
          type="warning"
          :closable="false"
          show-icon
          class="deployment-alert"
          :description="t('programUpdate.container')"
        />
        <p v-else-if="!info.supported" class="deployment-note">{{ t('programUpdate.unsupported') }}</p>
      </div>

      <div v-if="info.supported" class="update-panels">
        <div class="update-panel online-panel">
          <div class="panel-header">
            <h3 class="panel-title"><el-icon aria-hidden="true"><Download /></el-icon>{{ t('programUpdate.onlineTitle') }}</h3>
            <el-button link size="small" :icon="Refresh" :loading="releasesLoading" :disabled="busy" @click="loadReleases">
              {{ t('programUpdate.refreshReleases') }}
            </el-button>
          </div>
          <p class="panel-desc">{{ t('programUpdate.onlineDesc') }}</p>

          <div class="online-fields">
            <div class="online-field">
              <label for="update-version-select" class="field-label">{{ t('programUpdate.versionLabel') }}</label>
              <el-select
                id="update-version-select"
                v-model="selectedVersion"
                :disabled="busy || releasesLoading"
                :aria-label="t('programUpdate.versionLabel')"
                class="full-select"
              >
                <el-option
                  v-for="option in versionOptions"
                  :key="option.value"
                  :value="option.value"
                  :label="versionDisplayName(option)"
                >
                  <div class="select-option-row">
                    <span>{{ option.isLatestOption ? t('programUpdate.latestStable') : option.version }}</span>
                    <span class="select-option-meta">
                      <el-tag v-if="!option.isLatestOption && option.channel === 'dev'" size="small" type="warning" effect="plain">DEV</el-tag>
                      <el-tag v-else-if="!option.isLatestOption" size="small" type="success" effect="plain">{{ t('programUpdate.stableTag') }}</el-tag>
                      <span v-if="option.isLatestOption && option.version" class="option-version-note">{{ option.version }}</span>
                      <span v-else-if="!option.isLatestOption && option.version === info.version" class="option-current-note">{{ t('programUpdate.currentTag') }}</span>
                    </span>
                  </div>
                </el-option>
              </el-select>
            </div>

            <div class="online-field">
              <label for="update-source-select" class="field-label">{{ t('programUpdate.sourceLabel') }}</label>
              <el-select
                id="update-source-select"
                v-model="selectedSource"
                :disabled="busy || releasesLoading"
                :aria-label="t('programUpdate.sourceLabel')"
                class="full-select"
              >
                <el-option
                  v-for="option in sourceOptions"
                  :key="option.value"
                  :value="option.value"
                  :label="sourceDisplayName(option)"
                >
                  <div class="select-option-row">
                    <span>{{ sourceDisplayName(option) }}</span>
                    <span v-if="option.isAutoOption" class="option-version-note">{{ t('programUpdate.autoSourceHint') }}</span>
                  </div>
                </el-option>
              </el-select>
            </div>
          </div>

          <el-alert
            v-if="isDevSelected"
            type="warning"
            :closable="false"
            show-icon
            class="panel-alert"
            :description="t('programUpdate.devWarning')"
          />

          <p v-if="releasesError" class="panel-error">{{ releasesError }}</p>
          <p v-else-if="releases && !selectedVersionEntry" class="panel-hint">{{ t('programUpdate.noVersionForPlatform') }}</p>
          <p v-else-if="selectedVersionEntry && !selectedVersionEntry.sources?.length" class="panel-hint">{{ t('programUpdate.noSourceAvailable') }}</p>

          <div v-if="onlineBusy" class="online-progress" role="status" aria-live="polite">
            <el-progress :percentage="onlineProgressPercent" :indeterminate="onlineIndeterminate" :duration="2" />
            <p class="progress-text">
              {{ onlineStatusText }}
              <span v-if="onlineState?.latencyMs" class="latency-note">({{ onlineState.latencyMs }} ms)</span>
            </p>
          </div>

          <div class="panel-actions">
            <el-button
              v-if="onlineCanCancel"
              :icon="Close"
              :loading="cancelingOnline"
              @click="cancelOnlineUpdate"
            >
              {{ t('common.cancel') }}
            </el-button>
            <el-button
              type="primary"
              :icon="Download"
              :loading="onlineBusy"
              :disabled="!canStartOnline"
              @click="startOnlineUpdate"
            >
              {{ t('programUpdate.startOnline') }}
            </el-button>
          </div>
        </div>

        <div class="update-panel manual-panel">
          <div class="panel-header">
            <h3 class="panel-title"><el-icon aria-hidden="true"><Upload /></el-icon>{{ t('programUpdate.manualTitle') }}</h3>
          </div>
          <i18n-t keypath="programUpdate.online" tag="p" class="panel-desc">
            <template #registry><a href="https://taoapi.dr34m.cn/" target="_blank" rel="noopener noreferrer">{{ t('programUpdate.registry') }}</a></template>
          </i18n-t>
          <p class="source-warning"><el-icon aria-hidden="true"><Warning /></el-icon><span>{{ t('programUpdate.source') }} <a href="https://github.com/dr34m-cn/taosync/releases" target="_blank" rel="noopener noreferrer">GitHub Releases</a></span></p>
          <div class="update-controls">
            <el-upload :file-list="files" drag :auto-upload="false" :disabled="busy" :on-change="select" :on-remove="() => files = []">
              <el-icon :size="28" class="upload-icon" aria-hidden="true"><UploadFilled /></el-icon>
              <div class="el-upload__text">{{ t('programUpdate.drop') }} <em>{{ t('programUpdate.select') }}</em></div>
              <div class="upload-hint">{{ t('programUpdate.hint') }}</div>
            </el-upload>
            <div class="panel-actions">
              <el-button plain :icon="Refresh" :loading="phase === 'upload' || phase === 'restart'" :disabled="!file || busy || phase === 'unknown'" @click="install">{{ t('programUpdate.install') }}</el-button>
            </div>
          </div>
        </div>
      </div>

      <p v-else class="source-warning"><el-icon aria-hidden="true"><Warning /></el-icon><span>{{ t('programUpdate.source') }} <a href="https://github.com/dr34m-cn/taosync/releases" target="_blank" rel="noopener noreferrer">GitHub Releases</a></span></p>
    </div>

    <div role="status" aria-live="polite" class="update-status" :class="{ 'is-error': phase === 'error' || phase === 'rollback' }">
      <el-progress v-if="phase === 'upload'" :percentage="progress" />
      <p v-if="phase === 'upload'">{{ t(progress < 100 ? 'programUpdate.uploading' : 'programUpdate.verifying') }}</p>
      <p v-if="message">{{ message }}</p>
    </div>
    <div v-if="phase === 'unknown' || phase === 'started' || (!info && phase === 'error')" class="recovery-actions">
      <el-button v-if="phase === 'unknown' || (!info && phase === 'error')" :icon="Refresh" @click="load">{{ t('retry') }}</el-button>
      <el-button v-if="phase === 'unknown'" @click="stopWaiting">{{ t('programUpdate.stopWait') }}</el-button>
      <el-button v-if="phase === 'started'" :icon="Refresh" @click="reloadFrontend(info.result.id)">{{ t('programUpdate.reload') }}</el-button>
    </div>
  </section>
</template>

<style scoped>
.update-body { display: grid; gap: 16px; }
.platform-info {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px 20px;
  margin: 0;
  padding: 14px 16px;
  border-radius: 8px;
  background: var(--background-color);
}
.platform-item { min-width: 0; }
.platform-info dt, .program-update p, .upload-hint { color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.platform-info dd { margin: 4px 0 0; font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.deployment-note { margin: 10px 0 0; }
.deployment-alert { margin-top: 12px; border-radius: 8px; }
.panel-alert { border-radius: 8px; }
.deployment-alert :deep(.el-alert__description),
.panel-alert :deep(.el-alert__description) { margin-top: 0; font-size: 13px; line-height: 1.6; }
.update-panels { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; align-items: stretch; }
.update-panel {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: var(--background-color);
}
.panel-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.panel-title { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 15px; font-weight: 600; color: var(--text-primary); }
.panel-title .el-icon { color: var(--el-color-primary); }
.panel-desc { margin: 0; }
.panel-desc a { color: var(--el-color-primary); text-underline-offset: 3px; }
.online-fields { display: grid; gap: 12px; }
.online-field { display: grid; gap: 6px; }
.field-label { font-size: 13px; font-weight: 500; color: var(--text-primary); }
.full-select { width: 100%; }
.select-option-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; }
.select-option-meta { display: inline-flex; align-items: center; gap: 6px; }
.option-version-note, .option-current-note { font-size: 12px; color: var(--text-secondary); }
.panel-error { margin: 0; color: var(--el-color-danger) !important; }
.panel-hint { margin: 0; color: var(--el-color-warning) !important; }
.online-progress { display: grid; gap: 6px; }
.progress-text { margin: 0; font-size: 12px; }
.latency-note { margin-left: 4px; color: var(--text-secondary); }
.panel-actions { margin-top: auto; display: flex; justify-content: flex-end; gap: 8px; flex-wrap: wrap; }
.program-update .source-warning { display: flex; align-items: baseline; gap: 7px; margin: 0; }
.source-warning .el-icon { align-self: flex-start; margin-top: 3px; color: var(--el-color-warning); }
.source-warning a { color: var(--text-primary); text-underline-offset: 3px; }
.update-controls { min-width: 0; display: flex; flex-direction: column; gap: 10px; flex: 1; }
.update-controls :deep(.el-upload-dragger) { padding: 20px 14px; border-radius: 8px; background: var(--home-item-background-color); }
.update-controls :deep(.el-upload:focus-visible .el-upload-dragger) { outline: 2px solid var(--el-color-primary); }
.update-controls :deep(.el-upload-dragger.is-dragover) { background: var(--el-color-primary-light-9); }
.update-controls :deep(.el-upload-list:empty) { display: none; }
.upload-icon { color: var(--el-color-primary); }
.el-upload__text { margin: 3px 0; }
.upload-hint { font-size: 12px; }
.update-status:not(:empty) { margin-top: 14px; }
.update-status p { margin: 8px 0 0; }
.update-status.is-error p { color: var(--el-color-danger); }
.recovery-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.recovery-actions .el-button { margin: 0; }
@container (max-width: 760px) {
  .update-panels { grid-template-columns: minmax(0, 1fr); }
}
@container (max-width: 540px) {
  .platform-info { grid-template-columns: minmax(0, 1fr); gap: 10px; }
}
</style>
