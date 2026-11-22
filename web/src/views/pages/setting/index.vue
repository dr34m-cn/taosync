<script setup>
import { onMounted, ref } from "vue";
import { getSettings, updateSettings } from "@/api/settings";
import { parseTime } from "@/utils/utils";
import { useAppStore } from "@/store/useAppStore";
import { ElMessage } from "element-plus";
import { Check, Link, Operation, Refresh, User } from "@element-plus/icons-vue";
import { useI18n } from "vue-i18n";
import ProgramUpdate from './ProgramUpdate.vue';
import ApiKey from './ApiKey.vue';
import HttpsSettings from './HttpsSettings.vue';

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
  <main class="setting" aria-labelledby="settings-title">
    <header class="page-heading">
      <h1 id="settings-title">{{ $t('setting.title') }}</h1>
      <div v-if="appStore.user" class="account-info">
        <span><el-icon aria-hidden="true"><User /></el-icon>{{ $t('setting.username') }}: {{ appStore.user.userName }}</span>
        <span>{{ $t('common.createdAt') }}: {{ parseTime(appStore.user.createTime) }}</span>
      </div>
    </header>

    <section class="settings-section policy-section" aria-labelledby="policy-title" v-loading="loading" :aria-busy="loading">
      <h2 id="policy-title" class="section-heading"><el-icon aria-hidden="true"><Operation /></el-icon>{{ $t("setting.syncSettings") }}</h2>
      <el-form v-if="ready" ref="formRef" :model="form" :rules="rules" label-position="left" hide-required-asterisk :disabled="saving" @submit.prevent="save">
        <div class="settings-fields">
          <el-form-item v-for="key in numericFields" :key="key" :prop="key" :label="$t(`setting.${key}`)" class="setting-row policy-field">
            <template #label>
              <span class="field-label">{{ $t(`setting.${key}`) }}</span>
              <span :id="`${key}-hint`" class="field-note">{{ $t(`setting.${key}Hint`) }}</span>
            </template>
            <div class="number-control">
              <el-input-number v-model="form[key]" :min="0" :step="1" :precision="key === 'source_full_scan_days' ? undefined : 0"
                :aria-label="$t(`setting.${key}`)" :aria-describedby="`${key}-hint`" :controls="false" />
              <span class="field-unit">{{ $t(key === 'timeout' ? 'setting.hours' : 'setting.days') }}</span>
            </div>
          </el-form-item>
          <el-form-item class="setting-row auth-server" :label="$t('setting.aliyun_auth_server')">
            <template #label>
              <span class="field-label">{{ $t('setting.aliyun_auth_server') }}</span>
            </template>
            <el-input v-model="form.aliyun_auth_server" :aria-label="$t('setting.aliyun_auth_server')" :prefix-icon="Link" />
          </el-form-item>
        </div>
        <div class="form-actions">
          <details class="field-reference">
            <summary>{{ $t("setting.configKeys") }}</summary>
            <dl>
              <template v-for="key in [...numericFields, 'aliyun_auth_server']" :key="key">
                <dt>{{ $t(`setting.${key}`) }}</dt><dd><code>{{ key }}</code></dd>
              </template>
            </dl>
          </details>
          <el-button type="primary" native-type="submit" :icon="Check" :loading="saving">{{ $t('setting.saveAndApply') }}</el-button>
        </div>
      </el-form>
      <el-button v-else-if="!loading" @click="load" :icon="Refresh">{{ $t('retry') }}</el-button>
    </section>

    <HttpsSettings class="settings-section" />
    <ApiKey class="settings-section" />
    <ApiKey class="settings-section" scope="execute" />
    <ProgramUpdate class="settings-section" />
    <footer class="setting-footer">
      <span>{{ $t('setting.version') }}</span>
      <div>
        <a href="https://github.com/dr34m-cn/taosync" target="_blank" rel="noopener noreferrer">{{ $t('setting.github') }}</a>
        <a href="https://github.com/dr34m-cn/taosync/issues" target="_blank" rel="noopener noreferrer">{{ $t('setting.issues') }}</a>
      </div>
    </footer>
  </main>
</template>

<style scoped>
.setting {
  max-width: 1120px;
  margin-inline: auto;
  padding: 32px clamp(16px, 3.5%, 40px) 16px;
  box-sizing: border-box;
  color: var(--text-primary);
  font-family: var(--el-font-family);
  container-type: inline-size;
}
.page-heading, .account-info, .form-actions, .setting-footer, .setting-footer div {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}
.page-heading { gap: 12px 24px; justify-content: space-between; margin-bottom: 24px; }
h1 { margin: 0; font-size: 26px; font-weight: 650; line-height: 1.4; }
.account-info { gap: 4px 16px; }
.account-info span { min-width: 0; overflow-wrap: anywhere; }
.account-info .el-icon { margin-right: 6px; vertical-align: -2px; }
.account-info, .setting-footer { font-size: 12px; line-height: 1.6; color: var(--text-secondary); }
.settings-section {
  margin-bottom: 20px;
  padding: 24px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: var(--home-item-background-color);
}
.setting :deep(.section-heading) { display: flex; align-items: center; gap: 10px; margin: 0; font-size: 17px; font-weight: 600; line-height: 1.5; }
.setting :deep(.settings-section > .section-heading) { margin-bottom: 16px; }
.setting :deep(.section-toolbar) { display: flex; align-items: center; gap: var(--toolbar-gap, 12px); }
.setting :deep(.section-heading > .el-icon) { width: 32px; height: 32px; border-radius: 9px; background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.setting-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(160px, 42%);
  align-items: center;
  column-gap: 32px;
  margin: 0;
  padding-block: 20px;
}
.setting-row + .setting-row { border-top: 1px solid var(--border-color); }
.setting-row :deep(.el-form-item__label) { display: block; height: auto; padding: 0; line-height: 1.5; text-align: start; }
.setting-row :deep(.el-form-item__content) { min-width: 0; justify-content: flex-end; }
.field-label { display: block; color: var(--text-primary); font-size: 14px; font-weight: 500; overflow-wrap: anywhere; }
.field-note { display: block; margin-top: 5px; color: var(--text-secondary); font-size: 12px; line-height: 1.6; }
.number-control { display: flex; align-items: center; gap: 12px; }
.number-control .el-input-number { width: 120px; }
.field-unit { min-width: 28px; color: var(--text-secondary); font-size: 13px; }
.setting-row :deep(.el-input__wrapper) { min-height: 36px; box-sizing: border-box; border-radius: 7px; }
.setting-row :deep(input[type='number']) { -moz-appearance: textfield; appearance: textfield; }
.setting-row :deep(input[type='number']::-webkit-inner-spin-button),
.setting-row :deep(input[type='number']::-webkit-outer-spin-button) { -webkit-appearance: none; margin: 0; }
.form-actions {
  gap: 12px 24px;
  justify-content: space-between;
  align-items: flex-start;
  margin: 4px -24px -24px;
  padding: 16px 24px;
  border-top: 1px solid var(--border-color);
  border-radius: 0 0 12px 12px;
  background: var(--background-color);
}
.field-reference { min-width: 0; font-size: 12px; color: var(--text-secondary); }
.field-reference summary { line-height: 32px; cursor: pointer; }
.field-reference dl { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 6px 16px; margin: 8px 0 0; }
.field-reference dt, .field-reference dd { margin: 0; overflow-wrap: anywhere; }
.setting-footer { gap: 8px 20px; justify-content: space-between; padding-top: 0; }
.setting-footer div { gap: 8px 16px; }
.setting-footer a { color: inherit; text-underline-offset: 3px; }
.setting-footer a:hover, .field-reference summary:hover { color: var(--el-color-primary); }
@container (max-width: 600px) {
  .setting-row { grid-template-columns: minmax(0, 1fr); gap: 12px; padding-block: 16px; }
  .setting-row :deep(.el-form-item__content) { justify-content: flex-start; }
  .setting-row.is-error { padding-bottom: 28px; }
  .number-control { width: 100%; }
  .number-control .el-input-number { flex: 1; width: auto; }
}
@media (max-width: 768px) {
  .setting { padding: 20px 16px 16px; }
  .page-heading { display: grid; gap: 10px; margin-bottom: 20px; }
  h1 { font-size: 23px; }
  .account-info { gap: 4px 12px; }
  .settings-section { padding: 20px 16px; margin-bottom: 16px; }
  .form-actions { margin: 4px -16px -20px; padding: 16px; }
}
</style>
