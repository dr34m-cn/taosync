<script setup>
import { useMediaQuery } from "@vueuse/core";
import taskDesktop from "./taskDesktop.vue";
import taskMobile from "./taskMobile.vue";

const isMobile = useMediaQuery("(max-width: 768px)");
</script>

<template>
  <taskMobile v-if="isMobile" />
  <taskDesktop v-else />
</template>
