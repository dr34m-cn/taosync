<template>
	<div class="taskCurrent">
		<div class="content-none-data" v-if="current === null">
			{{loading ? '加载中' : '作业未在进行中'}}
		</div>
		<div class="current-box" v-else>
			<taskCurrentEcharts class="current-echart-box" :taskCurrent="current"></taskCurrentEcharts>
			<div class="current-center-box">
				当前状态：扫描{{current.scanFinish ? '完成，' : ''}}同步中<br/>
				开始时间：{{current.createTime | timeStampFilter}}<br/>
				持续时间：{{formatSeconds(current.duration)}}<br/>
				同步速度(估算)：
			</div>
			<div class="current-task-box"></div>
		</div>
	</div>
</template>

<script>
	import {
		jobGetTaskCurrent
	} from "@/api/job";
	import menuRefresh from './menuRefresh';
	import taskCurrentEcharts from './taskCurrentEcharts';
	export default {
		name: 'Task',
		props: {
			jobId: {
				type: String,
				default: null
			}
		},
		components: {
			menuRefresh,
			taskCurrentEcharts
		},
		data() {
			return {
				loading: false,
				current: {
					'scanFinish': false,
					'num': {
						'wait': 400,
						'doing': 5,
						'success': 1200,
						'fail': 1,
						'other': 1
					},
					'size': {
						'wait': 200 * 1024 * 8,
						'doing': 3 * 1024 * 8,
						'success': 2400 * 1024 * 8,
						'fail': 1 * 1024 * 8,
						'other': 1
					},
					'createTime': 1749042892,
					'duration': 98661,
					'doingTask': [{
						'srcPath': '/A/',
						'dstPath': '/B/',
						'isPath': 0,
						'fileName': '1.log',
						'fileSize': 20,
						'status': 1,
						'type': 0,
						'progress': 55.7,
						'errMsg': null,
						'createTime': 1748785129
					}]
				}
			};
		},
		created() {
			this.getCurrent();
		},
		beforeDestroy() {},
		methods: {
			getCurrent() {

			},
			formatSeconds(seconds) {
			  const days = Math.floor(seconds / (24 * 3600));
			  const hours = Math.floor((seconds % (24 * 3600)) / 3600);
			  const minutes = Math.floor((seconds % 3600) / 60);
			  const secs = seconds % 60;
			  const timeUnits = [
			    { value: days, unit: '天' },
			    { value: hours, unit: '小时' },
			    { value: minutes, unit: '分钟' },
			    { value: secs, unit: '秒' }
			  ];
			  const nonZeroUnits = timeUnits.filter(unit => unit.value > 0);
			  if (nonZeroUnits.length === 0) return '0秒';
			  return nonZeroUnits.map(unit => `${unit.value}${unit.unit}`).join(' ');
			},
			show() {
				this.$emit('currentChange', 300);
			},
			hide() {
				this.$emit('currentChange', 0);
			}
		}
	}
</script>

<style lang="scss" scoped>
	.taskCurrent {
		.current-box {
			background-color: #100c2a;
			height: calc(100% - 12px);
			padding: 8px 0;
			width: 100%;
			box-sizing: border-box;
			display: flex;

			.current-echart-box {
				height: 100%;
				width: 40%;
				min-width: 390px;
				box-sizing: border-box;
				border-right: 1px dotted #fff;
			}
		}
	}
</style>