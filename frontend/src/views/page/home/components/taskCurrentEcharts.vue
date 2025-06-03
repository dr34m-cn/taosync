<template>
	<div class="taskCurrentEcharts" ref="taskCurrentEcharts"></div>
</template>

<script>
	import * as echarts from "echarts";
	export default {
		name: 'DlEcharts',
		props: {
			taskCurrent: {
				type: Array,
				default: []
			}
		},
		data() {
			return {
				chart: null
			};
		},
		watch: {
			taskCurrent(newVal, oldVal) {
				if (JSON.stringify(oldVal) != JSON.stringify(newVal)) {
					this.$nextTick(() => {
						this.initChart();
					});
				}
			}
		},
		created() {
			this.$nextTick(() => {
				this.initChart();
			});
		},
		beforeDestroy() {
			this.destroyChart();
		},
		methods: {
			destroyChart() {
				if (this.chart) {
					this.chart.dispose();
					this.chart = null;
				}
			},
			coventtypeToName(key) {
				const keyVal = {
					num: '数量',
					size: '大小'
				}
				return keyVal[key];
			},
			coventStatusToName(key) {
				const keyVal = {
					wait: '等待中',
					doing: '进行中',
					success: '成功',
					fail: '失败',
					other: '其他'
				}
				return keyVal[key];
			},
			initChart() {
				// 原始数据
				const rawData = {
					num: this.taskCurrent.num,
					size: this.taskCurrent.size
				};
				const vm = this;
				// 归一化数据
				function normalize(data) {
					const max = Math.max(...Object.values(data));
					return Object.fromEntries(
						Object.entries(data).map(([k, v]) => [k, v / max])
					);
				}

				const normalizedData = {
					num: normalize(rawData['num']),
					size: normalize(rawData['size'])
				};
				const categories = ['num', 'size'];
				const types = ['wait', 'doing', 'success', 'fail', 'other'];

				// 构造 series
				const series = types.map(type => ({
					name: `${type}`,
					type: 'bar',
					stack: 'total',
					emphasis: {
						focus: 'series'
					},
					label: {
						show: true,
						formatter: (params) => {
							const category = params.name;
							const type = params.seriesName;
							return rawData[category][type];
						}
					},
					data: categories.map(cat => normalizedData[cat][type])
				}));

				// ECharts 配置
				const option = {
					color: ['rgb(79, 89, 104)', 'rgb(64, 158, 255)', 'rgb(103, 194, 58)', 'rgb(245, 108, 108)',
						'rgb(230, 162, 60)'
					],
					tooltip: {
						trigger: 'axis',
						axisPointer: {
							type: 'shadow'
						},
						formatter: params => {
							const category = params[0].name;
							let result = `<b>${vm.coventtypeToName(category)}</b><br/>`;
							params.forEach(item => {
								const trueVal = rawData[category][item.seriesName];
								result += `${item.marker}${vm.coventStatusToName(item.seriesName)}: ${trueVal}<br/>`;
							});
							return result;
						}
					},
					legend: {
						show: false,
					},
					grid: {
						left: '2%',
						right: '2%',
						bottom: '3%',
						top: '25%',
						containLabel: true
					},
					xAxis: {
						type: 'value',
						show: false,
						splitLine: {
							show: false
						}
					},
					yAxis: {
						type: 'category',
						data: categories
					},
					series
				};
				if (!this.chart) {
					this.chart = echarts.init(this.$refs.taskCurrentEcharts, 'dark');
				}
				this.chart.setOption(option);
			},
			resize() {
				if (this.chart) {
					this.chart.resize();
				}
			}
		}
	}
</script>

<style lang="scss" scoped>
	.taskCurrentEcharts {}
</style>