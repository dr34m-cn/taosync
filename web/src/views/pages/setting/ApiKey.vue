<script setup>
import { computed, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { Key, QuestionFilled } from '@element-plus/icons-vue';
import { marked } from 'marked';
import ApiKeyRow from './ApiKeyRow.vue';
import guideZh from './api-key.md?raw';
import guideEn from './api-key.en.md?raw';

const help = ref(false);
const { t, locale } = useI18n();
const guideHtml = computed(() => marked.parse(locale.value === 'en' ? guideEn : guideZh));
</script>

<template>
  <section aria-labelledby="api-keys-title">
    <header class="section-toolbar">
      <h2 id="api-keys-title" class="section-heading"><el-icon aria-hidden="true"><Key /></el-icon>{{ t('apiKey.groupTitle') }}</h2>
      <el-button link type="primary" :icon="QuestionFilled" @click="help = true">{{ t('apiKey.help') }}</el-button>
    </header>
    <ApiKeyRow scope="general" />
    <ApiKeyRow scope="execute" />
    <el-dialog v-model="help" :title="t('apiKey.helpTitle')" width="min(640px, 92vw)" append-to-body>
      <article class="key-guide" v-html="guideHtml" />
    </el-dialog>
  </section>
</template>

<style scoped>
.key-guide { line-height: 1.65; }
.key-guide :deep(h3:first-child) { margin-top: 0; }
.key-guide :deep(pre) { padding: 12px; overflow-x: auto; background: var(--el-fill-color-light); border-radius: 6px; }
</style>
