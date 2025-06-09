<template>
	<div class="taskCurrent">
		<div class="content-none-data" v-if="current === null">
			{{loading ? '加载中' : '作业未在进行中'}}
		</div>
		<div class="current-box" v-else>
			<div class="current-box-top">
				<div class="top-line">
					<div style="display: flex;align-items: center;">
						整体进度：<span v-if="current.firstSync === null">暂未发现需同步文件</span>
						<el-progress v-else :stroke-width="20" :text-inside="true" style="width: 160px;"
							color="rgba(64, 158, 255, .8)" text-color="#fff" define-back-color="rgba(64, 158, 255, .3)"
							:percentage="Number(current.allProgress.toFixed(4))"></el-progress>
					</div>
					<div>当前状态：扫描{{current.scanFinish ? '完成，同步' : (current.firstSync === null ? '' : '并同步')}}中</div>
					<div>平均速度：
						<span v-if="current.firstSync === null">--</span>
						<span v-else>{{current.speedAvg | sizeFilter}}/s</span>
					</div>
					<div>瞬时速度：
						<span v-if="current.firstSync === null">--</span>
						<span v-else>{{current.speed | sizeFilter}}/s</span>
					</div>
				</div>
				<div class="top-line">
					<div>持续时间：{{current.durationText}}</div>
					<div>预计还要：{{current.firstSync === null ? '--' : current.remainTimeText}}</div>
					<div>开始时间：{{current.createTime | timeStampFilter}}</div>
					<div>预计完成：<span v-if="current.firstSync === null">--</span>
						<span
							v-else>{{(current.createTime + current.duration + current.remainTime) | timeStampFilter}}</span>
					</div>
				</div>
			</div>
			<div class="current-box-bottom">
				<div class="content-none-data" v-if="current.firstSync === null">扫描中，暂无需要同步的文件，请耐心等待...</div>
				<taskCurrentEcharts v-else class="current-echart-box" :taskCurrent="current"></taskCurrentEcharts>
				<div class="current-box-task">
					<div class="current-box-task-left">
						<div @click="changeTaskCu(0)"
							:class="`task-left-item${cuTaskSelect == 0 ? ' is-current' : ''}`">
							等待中</div>
						<div @click="changeTaskCu(1)"
							:class="`task-left-item${cuTaskSelect == 1 ? ' is-current' : ''}`">
							进行中</div>
						<div @click="changeTaskCu(2)"
							:class="`task-left-item${cuTaskSelect == 2 ? ' is-current' : ''}`">
							成功</div>
						<div @click="changeTaskCu(7)"
							:class="`task-left-item${cuTaskSelect == 7 ? ' is-current' : ''}`">
							失败</div>
						<div @click="changeTaskCu(-1)"
							:class="`task-left-item${cuTaskSelect == -1 ? ' is-current' : ''}`">
							其他
						</div>
					</div>
					<taskDetailTable class="current-box-task-right" :taskItemData="toTable" @pageChange="pageChange">
					</taskDetailTable>
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
	import taskDetailTable from "./taskDetailTable";
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
			taskCurrentEcharts,
			taskDetailTable
		},
		computed: {
			toTable() {
				const count = this.cuTaskList.length;
				let dataList = [];
				if (count != 0) {
					const startIndex = (this.toTableParams.pageNum - 1) * this.toTableParams.pageSize;
					dataList = this.cuTaskList.slice(startIndex, startIndex + this.toTableParams.pageSize);
				}
				return {
					dataList,
					count
				}
			}
		},
		data() {
			return {
				loading: false,
				loadingTask: false,
				timer: null,
				cuTaskSelect: 1,
				cuTaskList: [],
				toTableParams: {
					pageSize: 10,
					pageNum: 1
				},
				current: null

			};
		},
		created() {
			this.startRefresh();
			// this.test();
		},
		beforeDestroy() {
			this.endRefresh();
		},
		methods: {
			test() {
				let current = {
					'scanFinish': false,
					num: {
						"wait": 0,
						"running": 1,
						"success": 0,
						"fail": 0,
						"other": 0
					},
					size: {
						"wait": 0,
						"running": 134678,
						"success": 0,
						"fail": 0,
						"other": 0
					},
					'firstSync': 1749042992,
					'createTime': 1749042892,
					'duration': 661,
					'doingTask': [{
						'srcPath': '/A/',
						'dstPath': '/B/',
						'isPath': 0,
						'fileName': '1.log',
						'fileSize': 134678,
						'status': 1,
						'type': 0,
						'progress': 55.7,
						'errMsg': null,
						'createTime': 1748785129
					}]
				};
				this.dealWithCurrent(current);
			},
			startRefresh() {
				this.timer = setInterval(() => {
					this.getCurrent();
				}, 610);
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
					setTimeout(() => {
						this.loading = false;
					}, 9973);
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
					let calcs = this.calcSpeedAndSize(current);
					if (this.cuTaskSelect === 1) {
						this.cuTaskList = current.doingTask;
					}
					this.current = {
						...current,
						...calcs
					};
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
					setTimeout(() => {
						this.loadingTask = false;
					}, 9973);
				})
			},
			calcSpeedAndSize(current) {
				let doingSize = current.doingTask.reduce((sum, obj) => {
					return sum + obj.fileSize * obj.progress / 100.0;
				}, 0);
				// 执行中-未完成的文件大小
				let remainSize = current.size.running - doingSize + current.size.wait;
				let doneSize = current.size.success + doingSize;
				let speed = 0;
				if (this.current !== null) {
					speed = this.current.speed;
					if (current.duration - this.current.duration != 0 && doneSize - this.current.doneSize != 0) {
						speed = (doneSize - this.current.doneSize) / (current.duration - this.current.duration);
					}
				}
				let speedAvg = (doneSize) / (current.duration - current.firstSync + current.createTime);
				let remainTime = parseInt(remainSize / speedAvg);
				return {
					remainSize,
					doneSize,
					speedAvg,
					speed,
					remainTime,
					remainTimeText: this.formatSeconds(remainTime),
					allProgress: doneSize / (doneSize + remainSize) * 100
				}
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
			pageChange(val) {
				this.toTableParams = val;
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
				this.$emit('currentChange', 443);
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
			padding: 2px 10px;
			width: 100%;
			box-sizing: border-box;
			overflow-x: auto;

			.current-box-top {
				min-width: 1100px;
				box-sizing: border-box;
				height: 56px;
				padding: 3px 0;
				border-bottom: 1px dotted #fff;

				.top-line {
					display: flex;
					align-items: center;
					justify-content: center;

					div {
						width: 268px;
					}
				}
			}

			.current-box-bottom {
				min-width: 1100px;
				box-sizing: border-box;
				height: calc(100% - 66px);
				width: 100%;
				display: flex;

				.current-echart-box {
					height: 100%;
					width: 40%;
					min-width: 390px;
					box-sizing: border-box;
					border-right: 1px dotted #fff;
				}

				.content-none-data {
					width: 40%;
					box-sizing: border-box;
				}

				.current-box-task {
					width: 60%;
					height: 100%;
					box-sizing: border-box;
					padding: 8px 0 8px 12px;
					display: flex;

					.current-box-task-left {
						width: 60px;
						height: 100%;

						.task-left-item {
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
						margin-left: 8px;
						width: calc(100% - 68px);
						height: 100%
					}
				}
			}
		}
	}
</style>