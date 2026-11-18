<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import { Refresh, Upload, UploadFilled, Warning } from '@element-plus/icons-vue';
import axios from 'axios';

const endpoint = '/svr/settings/update';
const info = ref(null);
const files = ref([]);
const file = computed(() => files.value[0]?.raw);
const phase = ref('loading');
const message = ref('');
const progress = ref(0);
const busy = computed(() => ['confirm', 'upload', 'restart'].includes(phase.value));
const controller = new AbortController();
const receiptKey = 'taosync-program-update';
const signal = controller.signal;
let refreshTimer;

function reloadFrontend(id) {
  const url = new URL(window.location.href);
  url.searchParams.set('tao-update', id);
  // Change the document URL (before the hash route), not just the Vue route.
  window.location.replace(url.href);
}

async function status() {
  // Restart polling is deliberately quiet: a closed socket is expected here.
  const { data } = await axios.get(endpoint, { signal, timeout: 3500 });
  if (data.code !== 200) throw new Error(data.msg || '无法读取程序状态');
  return data.data;
}

async function waitForStart(id) {
  phase.value = 'restart';
  message.value = '文件已校验，正在等待服务重新启动…';
  const deadline = Date.now() + 180000;
  while (!signal.aborted && Date.now() < deadline) {
    try {
      info.value = await status();
      const result = info.value.result;
      if (result?.id === id && ['started', 'rollback'].includes(result.status)) {
        sessionStorage.removeItem(receiptKey);
        phase.value = result.status;
        message.value = result.status === 'started' ? '新程序已启动，正在载入新版页面…' : '新程序启动失败，已恢复到可用版本。';
        files.value = [];
        if (result.status === 'started') refreshTimer = setTimeout(() => reloadFrontend(id), 1000);
        return;
      }
    } catch { /* Service may be between processes. */ }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
  if (!signal.aborted) {
    phase.value = 'unknown';
    message.value = '尚未确认启动结果，请检查服务日志或重新查询。';
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
      ? '更新完成，新版页面已载入。' : '';
    if (refreshed) {
      url.searchParams.delete('tao-update');
      window.history.replaceState(window.history.state, '', url.href);
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
    message.value = '请选择非空且不超过 256 MiB 的可执行文件。';
  } else {
    files.value = [uploadFile];
  }
}

async function install() {
  if (busy.value || !file.value) return;
  phase.value = 'confirm';
  try {
    await ElMessageBox.confirm(`安装 ${file.value.name} 后将重启 TaoSync 并刷新页面。请先保存尚未提交的设置。`, '确认更新程序',
      { type: 'warning', confirmButtonText: '更新并重启', cancelButtonText: '取消' });
  } catch { phase.value = 'idle'; return; }
  progress.value = 0;
  phase.value = 'upload';
  message.value = '';
  try {
    const { data } = await axios.post(endpoint + '/upload', file.value, {
      signal, timeout: 600000,
      headers: { 'Content-Type': 'application/octet-stream', 'X-TaoSync-Update': '1' },
      onUploadProgress: event => { progress.value = Math.round(100 * event.loaded / file.value.size); },
    });
    if (!data.data?.id) throw new Error(data.msg || '未收到更新确认');
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
    <h2 id="program-update-title" class="section-heading"><el-icon aria-hidden="true"><Upload /></el-icon>程序更新</h2>
    <p v-if="phase === 'loading'">正在读取运行环境…</p>
    <div v-if="info" class="update-layout" :class="{ 'supports-upload': info.supported }">
      <div class="deployment">
        <dl class="platform-info">
          <dt>发布平台</dt><dd><code>{{ info.target }}</code></dd>
          <dt>处理器架构</dt><dd><code>{{ info.architecture }}</code></dd>
        </dl>
        <template v-if="info.supported">
          <p v-if="info.pinned">离线校验：仅接受部署时指定 SHA-256 的程序。</p>
          <p v-else>仅接受最新正式版中与当前平台匹配的可执行文件。</p>
          <p v-if="info.container">更新在当前容器重启后保留；重建容器会使用所选镜像的版本。</p>
        </template>
        <p v-else>当前为源码或移动端部署，请通过原安装方式更新。</p>
        <p class="source-warning"><el-icon aria-hidden="true"><Warning /></el-icon><span>切勿上传来历不明的可执行文件，建议从 <a href="https://github.com/dr34m-cn/taosync/releases" target="_blank" rel="noopener noreferrer">GitHub Releases</a> 下载。</span></p>
      </div>
      <div v-if="info.supported" class="update-controls">
        <el-upload :file-list="files" drag :auto-upload="false" :disabled="busy" :on-change="select" :on-remove="() => files = []">
          <el-icon :size="28" class="upload-icon" aria-hidden="true"><UploadFilled /></el-icon>
          <div class="el-upload__text">将可执行文件拖到此处，或<em>点击选择</em></div>
          <div class="upload-hint">请先解压发布包，文件最大 256 MiB</div>
        </el-upload>
        <el-button plain :icon="Refresh" :loading="busy" :disabled="!file || busy || phase === 'unknown'" @click="install">更新并重启</el-button>
      </div>
    </div>
    <div role="status" aria-live="polite" class="update-status" :class="{ 'is-error': phase === 'error' || phase === 'rollback' }">
      <el-progress v-if="phase === 'upload'" :percentage="progress" />
      <p v-if="phase === 'upload'">{{ progress < 100 ? '正在上传…' : '正在校验可执行文件…' }}</p>
      <p v-if="message">{{ message }}</p>
    </div>
    <div v-if="phase === 'unknown' || phase === 'started' || (!info && phase === 'error')" class="recovery-actions">
      <el-button v-if="phase === 'unknown' || (!info && phase === 'error')" :icon="Refresh" @click="load">重新查询</el-button>
      <el-button v-if="phase === 'unknown'" @click="stopWaiting">结束等待</el-button>
      <el-button v-if="phase === 'started'" :icon="Refresh" @click="reloadFrontend(info.result.id)">立即载入新版页面</el-button>
    </div>
  </section>
</template>

<style scoped>
.update-layout { display: grid; gap: 20px 32px; }
.update-layout.supports-upload { grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); }
.platform-info { display: grid; grid-template-columns: max-content minmax(0, 1fr); align-items: baseline; gap: 10px 16px; margin: 0; padding: 16px; border-radius: 8px; background: var(--background-color); }
.platform-info dt, .program-update p, .upload-hint { color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.platform-info dd { margin: 0; font-size: 14px; font-weight: 600; overflow-wrap: anywhere; }
.program-update p { margin: 10px 0 0; overflow-wrap: anywhere; }
.program-update .source-warning { display: flex; align-items: baseline; gap: 7px; margin-top: 14px; }
.source-warning .el-icon { align-self: flex-start; margin-top: 3px; color: var(--el-color-warning); }
.source-warning a { color: var(--text-primary); text-underline-offset: 3px; }
.update-controls { min-width: 0; display: grid; align-content: start; gap: 10px; }
.update-controls > .el-button { justify-self: end; }
.update-controls :deep(.el-upload-dragger) { padding: 24px 16px; border-radius: 8px; background: var(--background-color); }
.update-controls :deep(.el-upload:focus-visible .el-upload-dragger) { outline: 2px solid var(--el-color-primary); }
.update-controls :deep(.el-upload-dragger.is-dragover) { background: var(--el-color-primary-light-9); }
.update-controls :deep(.el-upload-list:empty) { display: none; }
.upload-icon { color: var(--el-color-primary); }
.el-upload__text { margin: 3px 0; }
.upload-hint { font-size: 12px; }
.update-status:not(:empty) { margin-top: 14px; }
.update-status.is-error p { color: var(--el-color-danger); }
.recovery-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.recovery-actions .el-button { margin: 0; }
@container (max-width: 700px) {
  .update-layout.supports-upload { grid-template-columns: minmax(0, 1fr); }
}
</style>
