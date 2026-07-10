<script setup>
import { useMediaQuery } from "@vueuse/core";
import taskDetailDesktop from "./taskDetailDesktop.vue";
import taskDetailMobile from "./taskDetailMobile.vue";

const isMobile = useMediaQuery("(max-width: 768px)");
</script>

<template>
  <taskDetailMobile v-if="isMobile" />
  <taskDetailDesktop v-else />
</template>
