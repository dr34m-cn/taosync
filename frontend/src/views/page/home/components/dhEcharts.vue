<template>
	<div class="dlEcharts" ref="dlEcharts"></div>
</template>

<script>
	import * as echarts from "echarts";
	export default {
		name: 'DlEcharts',
		props: {
			dlData: {
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
			dlData(newVal, oldVal) {
				if (JSON.stringify(oldVal) != JSON.stringify(newVal)) {
					this.$nextTick(() => {
						this.initChart();
					});
				}
			}
		},
		created() {
			this.$nextTick(() => {
				if (!this.chart) {
					this.initChart();
				}
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
			initChart() {
				// 原始数据
				const rawData = {
					'数量': {
						A: 10,
						B: 20,
						C: 30,
						D: 40,
						E: 50
					},
					'大小': {
						A: 1000000,
						B: 3000000,
						C: 2000000,
						D: 5000000,
						E: 4000000
					}
				};

				// 归一化数据
				function normalize(data) {
					const max = Math.max(...Object.values(data));
					return Object.fromEntries(
						Object.entries(data).map(([k, v]) => [k, v / max])
					);
				}

				const normalizedData = {
					'数量': normalize(rawData['数量']),
					'大小': normalize(rawData['大小'])
				};

				const categories = ['数量', '大小'];
				const types = ['A', 'B', 'C', 'D', 'E'];

				// 构造 series
				const series = types.map(type => ({
					name: `类别${type}`,
					type: 'bar',
					stack: 'total',
					emphasis: {
						focus: 'series'
					},
					label: {
						show: true,
						formatter: (params) => {
							const category = params.name; // 数量 or 大小
							const type = params.seriesName.replace('类别', '');
							return rawData[category][type]; // 显示真实值
						}
					},
					data: categories.map(cat => normalizedData[cat][type])
				}));

				// ECharts 配置
				option = {
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
							let result = `<b>${category}</b><br/>`;
							params.forEach(item => {
								const trueVal = rawData[category][item.seriesName.replace('类别', '')];
								result += `${item.marker}${item.seriesName}: ${trueVal}<br/>`;
							});
							return result;
						}
					},
					legend: {},
					grid: {
						left: '5%',
						right: '5%',
						bottom: '3%',
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
					this.chart = echarts.init(this.$refs.dlEcharts, 'dark');
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
	.dlEcharts {}
</style>