<script setup>
import * as echarts from 'echarts';
import { ref, watch, onMounted, onBeforeUnmount, nextTick } from "vue";
import { useDark } from "@vueuse/core";
const isDark = useDark();
const props = defineProps({
    options: {
        type: Object,
        default: null
    }
})
let chartInstance = null;
let resizeObserver = null;
const chartRef = ref();
const initChart = () => {
    if (!chartRef.value) return;
    const theme = isDark.value ? "dark" : "";
    chartInstance = echarts.init(chartRef.value, theme);

    if (props.options) {
        chartInstance.setOption(props.options);
    }

    if (window.ResizeObserver) {
        resizeObserver = new ResizeObserver(() => {
            chartInstance && chartInstance.resize();
        });
        resizeObserver.observe(chartRef.value);
    }
}

const disposeChart = () => {
    if (resizeObserver && chartRef.value) {
        resizeObserver.unobserve(chartRef.value);
        resizeObserver.disconnect();
        resizeObserver = null;
    }
    if (chartInstance) {
        chartInstance.dispose();
        chartInstance = null;
    }
};
watch(() => props.options, (newOptions) => {
    if (chartInstance && newOptions) {
        chartInstance.setOption(newOptions, true);
    }
}, { deep: true });
watch(isDark, async () => {
    disposeChart();
    await nextTick();
    initChart();
});
onMounted(async () => {
    await nextTick();
    initChart();
});

onBeforeUnmount(() => {
    disposeChart();
});
</script>

<template>
    <div class="echarts-box" ref="chartRef"></div>
</template>

<style lang="scss" scoped>
.echarts-box {
    width: 100%;
    height: 100%;
    min-height: 300px;
}
</style>
