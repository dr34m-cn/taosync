<script setup>
import { RefreshRight } from '@element-plus/icons-vue';
import taskStatus from '@/utils/taskStatus';
import taskProgress from './taskProgress.vue';

defineProps({ row: { type: Object, required: true }, submitting: Boolean });
defineEmits(['retry']);
</script>

<template>
  <div v-if="row.id && row.status === 7 && !row.isPath && row.fileName && [0, 1, 2].includes(row.type)" class="file-retry">
    <div v-if="row.retry" role="status">
      <span v-if="row.retry.queued">{{ $t('taskDetail.retryQueued') }}</span>
      <span v-else-if="row.retry.status === 2">{{ $t('taskDetail.retrySucceeded') }}</span>
      <span v-else-if="[3, 6].includes(row.retry.status)">{{ $t('taskDetail.retryFailed') }}</span>
      <span v-else>{{ $t('taskDetail.retryStatus', { status: taskStatus(row.retry.status) }) }}</span>
      <taskProgress v-if="row.retry.status === 1 && !row.retry.queued && row.type !== 1" :percentage="row.retry.progress" :stroke-width="16" />
      <div v-if="row.retry.errMsg" class="retry-error">{{ row.retry.errMsg }}</div>
    </div>
    <el-button v-if="!row.retry || row.retry.status > 2" size="small" type="primary" plain
      :icon="RefreshRight" :loading="submitting" @click.stop="$emit('retry', row)">{{ $t('retry') }}</el-button>
  </div>
</template>

<style scoped>
.file-retry { display: grid; gap: 4px; justify-items: start; margin-top: 4px; font-size: 12px; }
.file-retry > div { width: 100%; }
.retry-error { color: var(--fail-color); overflow-wrap: anywhere; }
</style>
