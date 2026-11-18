<script setup>
import { onMounted, ref } from "vue";
import { getSettings, updateSettings } from "@/api/settings";
import { parseTime } from "@/utils/utils";
import { useAppStore } from "@/store/useAppStore";
import { ElMessage } from "element-plus";
import { useI18n } from "vue-i18n";
import ProgramUpdate from './ProgramUpdate.vue';

const appStore = useAppStore();
const { t } = useI18n();
const form = ref({});
const formRef = ref();
const loading = ref(false);
const saving = ref(false);
const ready = ref(false);
const numericFields = ["task_save", "timeout", "source_full_scan_days"];
const rules = Object.fromEntries(numericFields.map(key => [key, [{ type: "number", required: true, min: 0, message: t(`setting.${key}`), trigger: "blur" }]]));

const load = async () => {
  loading.value = true;
  try {
    const { data } = await getSettings();
    form.value = { ...data };
    ready.value = true;
  } catch {
    ready.value = false;
  } finally {
    loading.value = false;
  }
};

const save = async () => {
  if (saving.value || !await formRef.value.validate().catch(() => false)) return;
  saving.value = true;
  try {
    const { data } = await updateSettings({ ...form.value });
    form.value = { ...data };
    ElMessage.success(t("setting.saved"));
  } catch {
    // Keep the draft available for retry after a failed save.
  } finally {
    saving.value = false;
  }
};

onMounted(load);
</script>

<template>
  <div class="setting">
    <div class="top-box">
      <div class="top-box-title">{{ $t("setting.title") }}</div>
    </div>
    <div class="account-info" v-if="appStore.user">
      <span>{{ $t("setting.username") }}: {{ appStore.user.userName }}</span>
      <span>{{ $t("common.createdAt") }}: {{ parseTime(appStore.user.createTime) }}</span>
    </div>
    <div class="setting-fields" v-loading="loading">
      <el-form v-if="ready" ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="saving">
        <el-form-item v-for="key in numericFields" :key="key" :prop="key" :label="$t(`setting.${key}`)">
          <div class="field-value">
            <el-input-number v-model="form[key]" :min="0" :step="1" :precision="key === 'source_full_scan_days' ? undefined : 0"
              :aria-label="$t(`setting.${key}`)" :controls="false" />
            <span>{{ $t(key === 'timeout' ? 'setting.hours' : 'setting.days') }}</span>
          </div>
          <div class="field-note">{{ key }} · {{ $t(`setting.${key}Hint`) }}</div>
        </el-form-item>
        <el-form-item :label="$t('setting.aliyun_auth_server')">
          <el-input v-model="form.aliyun_auth_server" :aria-label="$t('setting.aliyun_auth_server')" />
          <div class="field-note">aliyun_auth_server</div>
        </el-form-item>
        <el-button type="primary" :icon="'Check'" :loading="saving" @click="save">{{ $t("setting.saveAndApply") }}</el-button>
      </el-form>
      <el-button v-else-if="!loading" @click="load" :icon="'Refresh'">{{ $t("retry") }}</el-button>
    </div>
    <ProgramUpdate />
    <div class="setting-bottom">
      <span>{{ $t("setting.version") }}</span>
      <a href="https://github.com/dr34m-cn/taosync" target="_blank" rel="noopener noreferrer">{{ $t("setting.github") }}</a>
      <a href="https://github.com/dr34m-cn/taosync/issues" target="_blank" rel="noopener noreferrer">{{ $t("setting.issues") }}</a>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.setting {
  padding: 32px;
  width: 100%;
  min-height: 100%;
  box-sizing: border-box;
}
.account-info {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 28px;
  margin-bottom: 28px;
  color: var(--text-muted);
  overflow-wrap: anywhere;
}
.setting-fields {
  max-width: 600px;
  min-height: 280px;
}
.field-value {
  display: flex;
  align-items: center;
  gap: 12px;
}
.field-note {
  width: 100%;
  font-size: 12px;
  line-height: 1.6;
  margin-top: 6px;
  color: var(--text-muted);
  overflow-wrap: anywhere;
}
.setting-bottom {
  margin-top: 36px;
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
  font-size: 13px;
  color: var(--text-muted);
  a { color: var(--active-color); }
}
@media (max-width: 768px) {
  .setting { padding: 20px 12px 28px; }
  .setting-bottom { flex-direction: column; }
}
</style>
