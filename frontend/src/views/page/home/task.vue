<template>
	<div class="task">
		<div class="top-box">
			<el-button type="primary" icon="el-icon-back" @click="goback">返回</el-button>
			<div class="top-box-title">作业详情</div>
			<el-button :loading="loading" type="primary" icon="el-icon-refresh" circle @click="getTaskList"></el-button>
		</div>
		<el-table :data="taskData.dataList" class="table-data" height="calc(100% - 117px)" v-loading="loading"
			empty-text="暂无任务">
			<el-table-column type="index" label="序号" align="center" width="120"></el-table-column>
			<el-table-column prop="status" label="状态" width="140">
				<template slot-scope="scope">
					<div :class="`bg-status bg-${scope.row.status < 6 ? scope.row.status : 7}`">
						<template v-if="scope.row.status == 1 && scope.row.allNum == 0">
							扫描对比中
						</template>
						<template v-else-if="scope.row.status == 2 && scope.row.allNum == 0">
							无需同步
						</template>
						<template v-else>
							<span v-if="scope.row.status != 6">
								{{scope.row.status | taskStatusFilter}}
							</span>
							<el-popover v-else placement="top-end" title="错误原因" width="200" trigger="hover"
								:content="scope.row.errMsg">
								<span slot="reference">失败，<span style="color: #409eff;">原因</span></span>
							</el-popover>
						</template>
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="successNum" label="任务进度（意义见页面底部图例，单位个）">
				<template slot-scope="scope">
					<div style="display: flex;align-items: center;flex-wrap: wrap;">
						<span class="prgNum bg-8">{{scope.row.allNum}}</span>
						<span class="prgNum bg-2">{{scope.row.successNum}}</span>
						<span class="prgNum bg-1">{{scope.row.runningNum}}</span>
						<span class="prgNum bg-0">{{scope.row.waitNum}}</span>
						<span class="prgNum bg-7">{{scope.row.failNum}}</span>
						<span class="prgNum bg-3">{{scope.row.otherNum}}</span>
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="alarmTime" label="创建时间" width="170">
				<template slot-scope="scope">
					{{scope.row.createTime | timeStampFilter}}
				</template>
			</el-table-column>
			<el-table-column label="操作" width="300">
				<template slot-scope="scope">
					<el-button type="danger" icon="el-icon-delete" @click="delTask(scope.row.id)" :loading="btnLoading"
						:disabled="scope.row.status == 1" size="small">{{scope.row.status == 1 ? '进行中的任务无法' : ''}}删除</el-button>
					<el-button type="primary" icon="el-icon-view" @click="detail(scope.row.id)" :loading="btnLoading" size="small"
						v-if="scope.row.allNum != 0">详情</el-button>
				</template>
			</el-table-column>
		</el-table>
		<div class="page">
			<div class="page-tip">
				<span style="margin-right: 12px;">进度图例：</span>
				<span class="prgNum bg-8">需同步文件总数</span>
				<span class="prgNum bg-2">成功数</span>
				<span class="prgNum bg-1">进行中</span>
				<span class="prgNum bg-0">等待中</span>
				<span class="prgNum bg-7">失败数</span>
				<span class="prgNum bg-3">其他（等待重试、已取消等）</span>
			</div>
			<el-pagination @size-change="handleSizeChange" @current-change="handleCurrentChange"
				:current-page="params.pageNum" :page-size="params.pageSize" :total="taskData.count"
				layout="total, sizes, prev, pager, next, jumper" :page-sizes="[10, 20, 50, 100]">
			</el-pagination>
		</div>
	</div>
</template>

<script>
	import {
		jobGetTask,
		jobDeleteTask
	} from "@/api/job";
	export default {
		name: 'Task',
		components: {},
		data() {
			return {
				taskData: {
					dataList: [],
					conut: 0
				},
				params: {
					id: null,
					pageSize: 10,
					pageNum: 1
				},
				loading: false,
				btnLoading: false
			};
		},
		created() {
			if (this.$route.query.hasOwnProperty('jobId')) {
				this.params.id = this.$route.query.jobId;
			}
			this.getTaskList();
		},
		beforeDestroy() {},
		methods: {
			getTaskList() {
				if (this.params.id != null) {
					this.loading = true;
					jobGetTask(this.params).then(res => {
						this.loading = false;
						this.taskData = res.data;
					}).catch(err => {
						this.loading = false;
					})
				}
			},
			delTask(taskId) {
				this.$confirm("操作不可逆，将永久删除该记录，确定吗？", '提示', {
					confirmButtonText: '确定',
					cancelButtonText: '取消',
					type: 'warning'
				}).then(() => {
					this.btnLoading = true;
					jobDeleteTask(taskId).then(res => {
						this.btnLoading = false;
						this.$message({
							message: res.msg,
							type: 'success'
						});
						this.getTaskList();
					}).catch(err => {
						this.btnLoading = false;
					})
				});
			},
			detail(taskId) {
				this.$router.push({
					path: '/home/task/detail',
					query: {
						taskId
					}
				})
			},
			goback() {
				this.$router.go(-1);
			},
			handleSizeChange(val) {
				this.params.pageSize = val;
				this.getTaskList();
			},
			handleCurrentChange(val) {
				this.params.pageNum = val;
				this.getTaskList();
			}
		}
	}
</script>

<style lang="scss" scoped>
	.task {
		width: 100%;
		height: 100%;
		padding: 16px;
		box-sizing: border-box;

		.top-box {
			display: flex;
			align-items: center;
			justify-content: space-between;
			margin-bottom: 16px;

			.top-box-title {
				font-weight: bold;
			}
		}

		.prgNum {
			padding: 1px 6px;
			text-align: center;
			font-weight: bold;
			margin: 2px 3px;
			min-width: 56px;
			border-radius: 3px;
		}

		.prgNum:last-child {
			margin-right: 0;
		}

		.page {
			margin-top: 24px;
			display: flex;
			align-items: center;
			justify-content: space-between;
		}
	}
</style>