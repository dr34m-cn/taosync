<script setup>
import { ref } from 'vue';
import { ElMessage } from 'element-plus';
import { RefreshRight } from '@element-plus/icons-vue';
import { useI18n } from 'vue-i18n';
import { jobPut } from '@/api/job';

const props = defineProps({ taskId: { type: [String, Number], required: true } });
const emit = defineEmits(['submitted']);
const { t } = useI18n();
const busy = ref(false);

async function submit() {
  if (busy.value) return;
  busy.value = true;
  try {
    const { data } = await jobPut({ action: 'retryAll', taskId: props.taskId });
    ElMessage.success(data.count ? t('taskDetail.addedRetries', { count: data.count }) : t('taskDetail.noRetries'));
    emit('submitted');
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <el-button type="primary" size="small" plain :icon="RefreshRight" :loading="busy" @click.stop="submit">
    {{ t('taskDetail.retryAll') }}
  </el-button>
</template>
