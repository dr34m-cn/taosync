<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { ElMessageBox } from 'element-plus';
import { Refresh, Upload } from '@element-plus/icons-vue';
import axios from 'axios';

const endpoint = '/svr/settings/update';
const info = ref(null);
const file = ref(null);
const release = ref('');
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
        file.value = null;
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

function select(event) {
  file.value = event.target.files[0] || null;
  message.value = '';
  if (file.value && (!file.value.size || file.value.size > info.value.maxBytes)) {
    file.value = null;
    event.target.value = '';
    message.value = '请选择非空且不超过 256 MiB 的可执行文件。';
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
      headers: { 'Content-Type': 'application/octet-stream', 'X-TaoSync-Update': '1', 'X-TaoSync-Release': release.value.trim() },
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
    <h2 id="program-update-title">程序更新</h2>
    <p v-if="phase === 'loading'">正在读取运行环境…</p>
    <template v-if="info">
      <p>处理器架构：<strong>{{ info.architecture }}</strong> · <code>{{ info.target }}</code></p>
      <template v-if="info.supported">
        <p>请选择对应平台发布包内的可执行文件，不要上传压缩包。</p>
        <p v-if="info.container">更新在当前容器重启后保留；重建容器会使用所选镜像的版本。</p>
        <label v-if="!info.pinned">发布标签
          <el-input v-model="release" placeholder="留空使用最新正式版" :disabled="busy" maxlength="65" />
        </label>
        <p v-else>离线校验：仅接受部署时指定 SHA-256 的程序。</p>
        <label>可执行文件（最多 256 MiB）
          <input :key="phase === 'started' || phase === 'rollback'" type="file" :disabled="busy" @change="select" />
        </label>
        <el-button type="primary" :icon="Upload" :loading="busy" :disabled="!file || busy || phase === 'unknown'" @click="install">
          更新并重启
        </el-button>
      </template>
      <p v-else>当前为源码或移动端部署，请通过原安装方式更新。</p>
    </template>
    <div role="status" aria-live="polite">
      <el-progress v-if="phase === 'upload'" :percentage="progress" />
      <p v-if="phase === 'upload'">{{ progress < 100 ? '正在上传…' : '正在校验可执行文件…' }}</p>
      <p v-if="message">{{ message }}</p>
    </div>
    <el-button v-if="phase === 'unknown' || (!info && phase === 'error')" :icon="Refresh" @click="load">重新查询</el-button>
    <el-button v-if="phase === 'unknown'" @click="stopWaiting">结束等待</el-button>
    <el-button v-if="phase === 'started'" :icon="Refresh" @click="reloadFrontend(info.result.id)">立即载入新版页面</el-button>
  </section>
</template>

<style scoped>
.program-update { max-width: 600px; margin-top: 32px; border-top: 1px solid var(--el-border-color); padding-top: 16px; }
h2 { font-size: 17px; margin: 0 0 12px; }
p { font-size: 13px; color: var(--text-muted); line-height: 1.6; overflow-wrap: anywhere; }
strong, code { color: var(--el-text-color-primary); }
label { display: grid; gap: 6px; font-size: 14px; margin: 14px 0; }
input { max-width: 100%; min-width: 0; font: inherit; }
.el-progress { margin-top: 12px; }
</style>
