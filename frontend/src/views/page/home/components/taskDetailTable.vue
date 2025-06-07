<template>
	<div class="taskDetailTable">
		<el-table :data="taskItemData.dataList" class="table-data" height="calc(100% - 36px)" v-loading="loading"
			empty-text="无数据">
			<el-table-column type="expand">
				<template slot-scope="props">
					<div class="form-box">
						<div class="form-box-item" v-if="props.row.type != 1">
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
			<el-table-column prop="fileName" label="文件名/目录">
				<template slot-scope="scope">
					{{scope.row.isPath ? scope.row.dstPath : scope.row.fileName}}
				</template>
			</el-table-column>
			<el-table-column prop="fileSize" label="文件大小" width="120">
				<template slot-scope="scope">
					{{scope.row.fileSize | sizeFilter}}
				</template>
			</el-table-column>
			<el-table-column prop="type" label="操作类型" width="90">
				<template slot-scope="scope">
					<div :class="`bg-status bg-${scope.row.type ? '3' : '8'}`" style="width: 50px;">
						{{scope.row.type == 0 ? (scope.row.isPath ? '创建' : '复制') : (scope.row.type == 1 ? '删除' : '移动')}}
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="status" label="状态" width="120">
				<template slot-scope="scope">
					<div :class="`bg-status bg-${scope.row.status}`" v-if="scope.row.status != 1">
						<span v-if="scope.row.status != 7">
							{{scope.row.status | taskItemStatusFilter}}
						</span>
						<el-popover v-else placement="top-end" title="错误原因" width="200" trigger="hover"
							:content="scope.row.errMsg">
							<span slot="reference">失败，<span style="color: #409eff;">原因</span></span>
						</el-popover>
					</div>
					<el-progress :stroke-width="20" v-else :text-inside="true" style="width: 90px;"
						color="rgba(64, 158, 255, .8)" text-color="#fff" define-back-color="rgba(64, 158, 255, .3)"
						:percentage="Number(Number(scope.row.progress).toFixed(2))"></el-progress>
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
	export default {
		name: 'TaskDetailTable',
		props: {
			taskItemData: {
				type: Object,
				default: {
					dataList: [],
					conut: 0
				}
			},
			loading: {
				type: Boolean,
				default: false
			}
		},
		data() {
			return {
				params: {
					pageSize: 10,
					pageNum: 1
				}
			};
		},
		created() {},
		beforeDestroy() {},
		methods: {
			handleSizeChange(val) {
				this.params.pageSize = val;
				this.$emit("pageChange", this.params);
			},
			handleCurrentChange(val) {
				this.params.pageNum = val;
				this.$emit("pageChange", this.params);
			}
		}
	}
</script>

<style lang="scss" scoped>
	.taskDetailTable {
		:deep(.el-progress-bar__outer) {
			border-radius: 4px;
			
			.el-progress-bar__inner {
				border-radius: 4px;
			}
		}
		.page {
			margin-top: 8px;
			display: flex;
			justify-content: right;
		}
	}
</style>