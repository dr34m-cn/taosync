<template>
	<div class="taskCurrentEcharts" ref="taskCurrentEcharts"></div>
</template>

<script>
	import * as echarts from "echarts";
	export default {
		name: 'DlEcharts',
		props: {
			taskCurrent: {
				type: Object,
				default: {}
			}
		},
		data() {
			return {
				chart: null,
				observer: null
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
				this.initResizeObserver();
			});
		},
		beforeDestroy() {
			this.destroy();
		},
		methods: {
			destroy() {
				if (this.chart) {
					this.chart.dispose();
					this.chart = null;
				}
				if (this.observer) {
					this.observer.disconnect();
				}
			},
			initResizeObserver() {
				const element = this.$refs.taskCurrentEcharts;
				this.observer = new ResizeObserver(entries => {
					for (const entry of entries) {
						this.resize();
					}
				});
				this.observer.observe(element);
			},
			initChart() {
				// 原始数据
				const rawData = {
					num: this.taskCurrent.num,
					size: this.taskCurrent.size
				};
				const keyVal = {
					wait: '等待中',
					doing: '进行中',
					success: '成功',
					fail: '失败',
					other: '其他'
				};
				let d0 = [];
				Object.entries(keyVal).forEach(([key, val]) => {
					d0.push({
						name: val,
						value: this.taskCurrent.num[key]
					})
				})
				let d1 = [];
				Object.entries(keyVal).forEach(([key, val]) => {
					d1.push({
						name: val,
						value: this.taskCurrent.size[key]
					})
				})
				// ECharts 配置
				const option = {
					color: ['rgb(79, 89, 104)', 'rgb(64, 158, 255)', 'rgb(103, 194, 58)', 'rgb(245, 108, 108)',
						'rgb(230, 162, 60)'
					],
					tooltip: {
						trigger: 'item'
					},
					legend: {
						top: '5%',
						left: 'center'
					},
					series: [{
						name: '文件及目录数量',
						type: 'pie',
						radius: ['75%', '90%'],
						center: ['50%', '86%'],
						startAngle: 180,
						endAngle: 360,
						data: d0
					}, {
						name: '文件大小',
						type: 'pie',
						radius: [0, '65%'],
						center: ['50%', '86%'],
						startAngle: 180,
						endAngle: 360,
						label: {
							position: 'inside'
						},
						data: d1
					}]
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