<template>
	<div class="taskCurrent">
		<div class="content-none-data" v-if="current === null">
			{{loading ? '加载中' : '作业未在进行中'}}
		</div>
		<div class="current-box" v-else>
			<div class="current-box-top">
				<div>当前状态：扫描{{current.scanFinish ? '完成，' : ''}}同步中</div>
				<div>平均同步速度(估算)：{{speedAvg | sizeFilter}}/s</div>
				<div>持续时间：{{durationText}}</div>
				<div>开始时间：{{current.createTime | timeStampFilter}}</div>
			</div>
			<div class="current-box-bottom">
				<taskCurrentEcharts class="current-echart-box" :taskCurrent="current"></taskCurrentEcharts>
				<div class="current-box-task">
					<div class="current-box-task-left">
						<div @click="changeTaskCu(0)" :class="`task-left-item${cuTaskSelect == 0 ? ' is-current' : ''}`">
							等待中</div>
						<div @click="changeTaskCu(1)" :class="`task-left-item${cuTaskSelect == 1 ? ' is-current' : ''}`">
							进行中</div>
						<div @click="changeTaskCu(2)" :class="`task-left-item${cuTaskSelect == 2 ? ' is-current' : ''}`">
							成功</div>
						<div @click="changeTaskCu(7)" :class="`task-left-item${cuTaskSelect == 7 ? ' is-current' : ''}`">
							失败</div>
						<div @click="changeTaskCu(-1)" :class="`task-left-item${cuTaskSelect == -1 ? ' is-current' : ''}`">
							其他
						</div>
					</div>
					<div class="current-box-task-right"></div>
				</div>
			</div>
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
				loadingTask: false,
				timer: null,
				cuTaskSelect: 1, // 0 1 2 7 -1
				cuTaskList: [],
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
					'duration': 661,
					'durationText': '1天',
					'speedAvg': 86400,
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
			// this.startRefresh();
		},
		beforeDestroy() {
			this.endRefresh();
		},
		methods: {
			startRefresh() {
				this.timer = setInterval(() => {
					this.getCurrent();
				}, 290);
			},
			endRefresh() {
				if (this.timer) {
					clearInterval(this.timer);
				}
			},
			getCurrent() {
				if (this.loading) {
					return
				}
				this.loading = true;
				jobGetTaskCurrent({
					id: this.jobId
				}).then(res => {
					this.dealWithCurrent(res.data);
				}).catch(err => {
					this.loading = false;
				})
			},
			dealWithCurrent(current) {
				if (current === null) {
					if (this.current !== null) {
						this.hide();
					}
					setTimeout(() => {
						this.loading = false;
					}, 9973);
				} else {
					if (this.current === null) {
						this.show();
					}
					current.durationText = this.formatSeconds(current.duration);
					current.speedAvg = this.calcSpeedAvg(current);
					if (this.cuTaskSelect === 1) {
						this.cuTaskList = current.doingTask;
					}
					this.current = current;
					this.loading = false;
					this.getTaskList();
				}
			},
			getTaskList() {
				if (this.current === null || this.loadingTask || this.cuTaskSelect === 1) {
					return
				}
				this.loadingTask = true;
				jobGetTaskCurrent({
					id: this.jobId,
					status: this.cuTaskSelect
				}).then(res => {
					this.cuTaskList = res.data;
					this.loadingTask = false;
				}).catch(err => {
					this.loadingTask = false;
				})
			},
			calcSpeedAvg(current) {
				let doingSize = current.doingTask.reduce((sum, obj) => {
					return sum + (sum, obj.fileSize * obj.progress);
				}, 0);
				return (current.size.success + doingSize) / current.duration;
			},
			changeTaskCu(status) {
				if (this.cuTaskSelect === status) {
					return
				}
				this.cuTaskSelect = status;
				if (status == 1) {
					this.cuTaskList = this.current.doingTask;
				} else {
					this.cuTaskList = [];
				}
			},
			formatSeconds(seconds) {
				const days = Math.floor(seconds / (24 * 3600));
				const hours = Math.floor((seconds % (24 * 3600)) / 3600);
				const minutes = Math.floor((seconds % 3600) / 60);
				const secs = seconds % 60;
				const timeUnits = [{
						value: days,
						unit: '天'
					},
					{
						value: hours,
						unit: '小时'
					},
					{
						value: minutes,
						unit: '分钟'
					},
					{
						value: secs,
						unit: '秒'
					}
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
			padding: 8px 10px;
			width: 100%;
			box-sizing: border-box;

			.current-box-top {
				display: flex;
				align-items: center;
				justify-content: center;
				padding: 6px 0;
				border-bottom: 1px dotted #fff;

				div {
					width: 268px;
				}
			}

			.current-box-bottom {
				height: calc(100% - 36px);
				width: 100%;
				display: flex;

				.current-echart-box {
					height: 100%;
					width: 40%;
					min-width: 390px;
					box-sizing: border-box;
					border-right: 1px dotted #fff;
				}

				.current-box-task {
					width: 60%;
					height: 100%;
					box-sizing: border-box;
					padding: 8px 12px;
					display: flex;

					.current-box-task-left {
						width: 60px;

						height: 100% .task-left-item {
							cursor: pointer;
							width: 60px;
							margin: 14px 0;
							padding: 3px 6px 3px 0;
							color: #4f5968;
							text-align: right;
							box-sizing: border-box;
						}

						.is-current {
							color: #409eff;
							border-right: 3px solid #409eff;
							background-color: rgba(64, 158, 255, 0.4);
						}
					}

					.current-box-task-right {
						width: calc(100% - 60px);
						height: 100%
					}
				}
			}
		}
	}
</style>