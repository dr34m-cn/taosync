<script setup>
import { computed } from 'vue';
import { ElConfigProvider } from 'element-plus';
import { LANGS } from '@/utils/langs';
import { useI18n } from 'vue-i18n';
const { locale } = useI18n();
const localeEl = computed(() => (LANGS[locale.value].elem));
</script>

<template>
  <el-config-provider :locale="localeEl">
    <router-view />
  </el-config-provider>
</template>

<style lang="scss">
body {
  margin: 0;
  padding: 0;
}
</style>
