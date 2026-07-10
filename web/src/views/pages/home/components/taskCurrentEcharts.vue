<script setup>
import { computed } from "vue";
import echartsCommon from "@/views/components/echartsCommon.vue";
import { parseSize } from "@/utils/utils";
import { useI18n } from "vue-i18n";

const props = defineProps({
  taskCurrent: {
    type: Object,
    default: () => ({}),
  },
});
const { t } = useI18n();

const chartOptions = computed(() => {
  const keyVal = {
    wait: t("current.wait"),
    running: t("current.running"),
    success: t("current.success"),
    fail: t("current.fail"),
    other: t("current.other"),
  };
  const numData = [];
  const sizeData = [];
  Object.entries(keyVal).forEach(([key, val]) => {
    numData.push({
      name: val,
      value: props.taskCurrent.num?.[key] || 0,
    });
    sizeData.push({
      name: val,
      value: props.taskCurrent.size?.[key] || 0,
    });
  });
  return {
    color: ["#697386", "#2563eb", "#2f9e44", "#e03131", "#e67700"],
    tooltip: {
      trigger: "item",
    },
    legend: {
      top: "5%",
      left: "center",
    },
    series: [
      {
        name: t("task.total"),
        type: "pie",
        radius: ["75%", "90%"],
        center: ["50%", "86%"],
        startAngle: 180,
        endAngle: 360,
        data: numData,
      },
      {
        name: t("taskDetail.fileSize"),
        type: "pie",
        radius: [0, "65%"],
        center: ["50%", "86%"],
        startAngle: 180,
        endAngle: 360,
        label: {
          position: "inside",
        },
        tooltip: {
          valueFormatter: (value) => parseSize(value),
        },
        data: sizeData,
      },
    ],
  };
});
</script>

<template>
  <echartsCommon :options="chartOptions" />
</template>
