<template>
	<div class="taskDetail">
		<div class="top-box">
			<div style="display: flex; align-items: center;">
				<el-button type="primary" icon="el-icon-back" @click="goback" size="small"
					style="margin-right: 12px;">返回</el-button>
				<el-select v-model="params.status" placeholder="筛选状态" @change="getTaskItemList" clearable
					style="margin-right: 12px;width: 160px;">
					<el-option :label="item" :value="index" v-for="(item, index) in taskItemStatusList"></el-option>
				</el-select>
				<el-select v-model="params.type" placeholder="筛选操作类型" @change="getTaskItemList" clearable style="width: 140px;">
					<el-option label="复制" :value="0"></el-option>
					<el-option label="删除" :value="1"></el-option>
				</el-select>
			</div>
			<div class="top-box-title">任务详情</div>
			<menuRefresh :freshInterval="9973" :loading="loading" @getData="getTaskItemList"></menuRefresh>
			<!-- <el-button :loading="loading" type="primary" icon="el-icon-refresh" circle @click="getTaskItemList"></el-button> -->
		</div>
		<el-table :data="taskItemData.dataList" class="table-data" height="calc(100% - 117px)" v-loading="loading"
			empty-text="暂未发现需要同步的文件">
			<el-table-column type="expand">
				<template slot-scope="props">
					<div class="form-box">
						<div class="form-box-item" v-if="props.row.type == 0">
							<div class="form-box-item-label">
								来源目录
							</div>
							<div class="form-box-item-value">
								{{props.row.srcPath}}
							</div>
						</div>
						<div class="form-box-item">
							<div class="form-box-item-label">
								目标目录
							</div>
							<div class="form-box-item-value">
								{{props.row.dstPath}}
							</div>
						</div>
						<div class="form-box-item">
							<div class="form-box-item-label">
								创建时间
							</div>
							<div class="form-box-item-value">
								{{props.row.createTime | timeStampFilter}}
							</div>
						</div>
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="fileName" label="文件名"></el-table-column>
			<el-table-column prop="fileSize" label="文件大小" width="120">
				<template slot-scope="scope">
					{{scope.row.fileSize | sizeFilter}}
				</template>
			</el-table-column>
			<el-table-column prop="type" label="操作类型" width="90">
				<template slot-scope="scope">
					<div :class="`bg-status bg-${scope.row.type ? '3' : '8'}`" style="width: 50px;">
						{{scope.row.type == 0 ? '复制' : '删除'}}
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="status" label="状态" width="120">
				<template slot-scope="scope">
					<div :class="`bg-status bg-${scope.row.status}`" v-if="scope.row.status != 1">
						<span v-if="scope.row.status != 7">
							{{scope.row.status | taskItemStatusFilter}}
						</span>
						<el-popover v-else placement="top-end" title="错误原因" width="200" trigger="hover" :content="scope.row.errMsg">
							<span slot="reference">失败，<span style="color: #409eff;">原因</span></span>
						</el-popover>
					</div>
					<el-progress :stroke-width="20" v-else :text-inside="true" style="width: 90px;" color="rgba(64, 158, 255, .8)"
						text-color="#fff" define-back-color="rgba(64, 158, 255, .3)" :percentage="scope.row.progress"></el-progress>
				</template>
			</el-table-column>
		</el-table>
		<div class="page">
			<el-pagination @size-change="handleSizeChange" @current-change="handleCurrentChange"
				:current-page="params.pageNum" :page-size="params.pageSize" :total="taskItemData.count"
				layout="total, sizes, prev, pager, next, jumper" :page-sizes="[10, 20, 50, 100]">
			</el-pagination>
		</div>
	</div>
</template>

<script>
	import {
		jobGetTaskItem
	} from "@/api/job";
	import taskItemStatus from '@/utils/taskItemStatus';
	import menuRefresh from './components/menuRefresh';
	export default {
		name: 'TaskDetail',
		components: {
			menuRefresh
		},
		data() {
			return {
				taskItemData: {
					dataList: [],
					conut: 0
				},
				params: {
					taskId: null,
					pageSize: 10,
					pageNum: 1,
					status: null
				},
				loading: false,
				btnLoading: false,
				taskId: null,
				taskItemStatusList: []
			};
		},
		created() {
			if (this.$route.query.hasOwnProperty('taskId')) {
				this.params.taskId = this.$route.query.taskId;
			}
			this.getTaskItemList();
			this.taskItemStatusList = taskItemStatus;
		},
		beforeDestroy() {},
		methods: {
			getTaskItemList() {
				if (this.params.taskId != null) {
					this.loading = true;
					jobGetTaskItem(this.params).then(res => {
						this.loading = false;
						res.data.dataList.forEach(item => {
							item.progress = parseInt(item.progress);
							item.progress = item.progress < 100 ? item.progress : 100;
						})
						this.taskItemData = res.data;
					}).catch(err => {
						this.loading = false;
					})
				}
			},
			goback() {
				this.$router.go(-1);
			},
			handleSizeChange(val) {
				this.params.pageSize = val;
				this.getTaskItemList();
			},
			handleCurrentChange(val) {
				this.params.pageNum = val;
				this.getTaskItemList();
			}
		}
	}
</script>

<style lang="scss" scoped>
	.taskDetail {
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

		.page {
			margin-top: 24px;
			display: flex;
			justify-content: right;
		}
	}
</style>