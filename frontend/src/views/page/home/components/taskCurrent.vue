<template>
	<div class="taskCurrent">
		<div class="content-none-data" v-if="current === null">
			{{loading ? '加载中' : '作业未在进行中'}}
		</div>
		<div class="current-box" v-else>
			<div class="current-box-top">
				<div class="current-center-box"></div>
				<div class="current-task-box"></div>
			</div>
			<taskCurrentEcharts class="current-echart-box" :taskCurrent="current"></taskCurrentEcharts>
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
				type: Number,
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
			height: calc(100% - 12px);
			width: 100%;
			box-sizing: border-box;
			
			.current-box-top {
				height: 60%;
				width: 100%;
				box-sizing: border-box;
			}
			
			.current-echart-box {
				height: 40%;
				width: 100%;
				box-sizing: border-box;
			}
		}
	}
</style>