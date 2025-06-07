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
				<el-select v-model="params.type" placeholder="筛选操作类型" @change="getTaskItemList" clearable
					style="width: 140px;">
					<el-option label="复制/创建" :value="0"></el-option>
					<el-option label="删除" :value="1"></el-option>
					<el-option label="移动" :value="2"></el-option>
				</el-select>
			</div>
			<div class="top-box-title">任务详情</div>
			<menuRefresh :freshInterval="9973" :autoRefresh="false" :loading="loading" :needShow="1"
				@getData="getTaskItemList"></menuRefresh>
			<!-- <el-button :loading="loading" type="primary" icon="el-icon-refresh" circle @click="getTaskItemList"></el-button> -->
		</div>
		<taskDetailTable class="table-page-box" :loading="loading" :taskItemData="taskItemData" @pageChange="pageChange"></taskDetailTable>
	</div>
</template>

<script>
	import {
		jobGetTaskItem
	} from "@/api/job";
	import taskItemStatus from '@/utils/taskItemStatus';
	import menuRefresh from './components/menuRefresh';
	import taskDetailTable from "./components/taskDetailTable";
	export default {
		name: 'TaskDetail',
		components: {
			menuRefresh,
			taskDetailTable
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
			pageChange(val) {
				this.params.pageSize = val.pageSize;
				this.params.pageNum = val.pageNum;
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

		.table-page-box {
			width: 100%;
			height: calc(100% - 54px);
		}
	}
</style>