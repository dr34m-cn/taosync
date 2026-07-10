<script setup>
import { useMediaQuery } from "@vueuse/core";
import desktopJobManagement from "./desktop.vue";
import mobileJobManagement from "./mobile.vue";

const isMobile = useMediaQuery("(max-width: 768px)");
</script>

<template>
  <mobileJobManagement v-if="isMobile" />
  <desktopJobManagement v-else />
</template>
