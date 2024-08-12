<template>
	<div class="home">
		<div class="top-box">
			<el-button type="success" icon="el-icon-plus" @click="addShow">新建作业</el-button>
			<div class="top-box-title">作业管理</div>
			<el-button :loading="loading" type="primary" icon="el-icon-refresh" circle @click="getJobList"></el-button>
		</div>
		<el-table :data="jobData.dataList" :default-expand-all="true" class="table-data" height="calc(100% - 117px)" v-loading="loading">
			<el-table-column type="expand">
				<template slot-scope="props">
					<div class="form-box">
						<div class="form-box-item">
							<div class="form-box-item-label">
								同步方式
							</div>
							<div class="form-box-item-value">
								{{props.row.method == 0 ? '仅新增' : '全同步'}}
							</div>
						</div>
						<div class="form-box-item">
							<div class="form-box-item-label">
								同步速度
							</div>
							<div class="form-box-item-value">
								{{props.row.speed == 0 ? '标准' : '快速'}}
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
						<div class="form-box-item">
							<div class="form-box-item-label">
								更多操作
							</div>
							<div class="form-box-item-value">
								<el-button type="warning" :loading="btnLoading" size="small" v-if="props.row.enable"
									@click="disableJobShow(props.row, false)">禁用</el-button>
								<el-button type="success" :loading="btnLoading" size="small" v-else
									@click="putJob(props.row.id, false)">启用</el-button>
								<el-button type="danger" :loading="btnLoading" size="small"
									@click="disableJobShow(props.row, true)">删除</el-button>
								<el-button type="warning" :loading="btnLoading" size="small"
									@click="editJobShow(props.row)">编辑</el-button>
								<el-button type="success" :loading="btnLoading" size="small"
									@click="putJob(props.row.id)">手动执行</el-button>
							</div>
						</div>
					</div>
				</template>
			</el-table-column>
			<el-table-column type="index" label="序号" align="center" width="60"></el-table-column>
			<el-table-column prop="enable" label="状态" align="center" width="80">
				<template slot-scope="scope">
					<div :class="`bg-status bg-${scope.row.enable ? '2' : '7'}`" style="width: 50px;">
						{{scope.row.enable ? '启用' : '禁用'}}
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="srcPath" label="来源目录" min-width="40">
				<template slot-scope="scope">
					<div class="pathList">
						<div class="pathBox bg-8">{{scope.row.srcPath}}</div>
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="dstPath" label="目标目录" min-width="120">
				<template slot-scope="scope">
					<div class="pathList">
						<div class="pathBox bg-1" v-for="item in scope.row.dstPath.split(':')">{{item}}</div>
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="interval" label="同步间隔" width="120">
				<template slot-scope="scope">
					{{scope.row.interval}} 分钟
				</template>
			</el-table-column>
			<el-table-column label="操作" align="center" width="100">
				<template slot-scope="scope">
					<!-- <el-button type="warning" :loading="btnLoading" size="small" @click="disableJobShow(scope.row, false)"
						v-if="scope.row.enable">禁用</el-button>
					<el-button type="success" :loading="btnLoading" size="small" @click="putJob(scope.row.id, false)"
						v-else>启用</el-button>
					<el-button type="danger" :loading="btnLoading" size="small"
						@click="disableJobShow(scope.row, true)">删除</el-button>
					<el-button type="warning" :loading="btnLoading" size="small" @click="editJobShow(scope.row)">编辑</el-button>
					<el-button type="success" :loading="btnLoading" size="small" @click="putJob(scope.row.id)">手动执行</el-button> -->
					<el-button type="primary" @click="detail(scope.row.id)" :loading="btnLoading" size="small">详情</el-button>
				</template>
			</el-table-column>
		</el-table>
		<div class="page">
			<el-pagination @size-change="handleSizeChange" @current-change="handleCurrentChange"
				:current-page="params.pageNum" :page-size="params.pageSize" :total="jobData.count"
				layout="total, sizes, prev, pager, next, jumper" :page-sizes="[10, 20, 50, 100]">
			</el-pagination>
		</div>
		<el-dialog top="5vh" :close-on-click-modal="false" :visible.sync="editShow" :append-to-body="true"
			:title="`${editData && editData.id != null ? '编辑' : '新增'}作业`" width="460px" :before-close="closeShow">
			<div class="elform-box">
				<el-form :model="editData" :rules="addRule" ref="jobRule" v-if="editShow" label-width="80px">
					<el-form-item prop="enable" label="是否启用">
						<el-switch v-model="editData.enable" :active-value="1" :inactive-value="0">
						</el-switch>
					</el-form-item>
					<el-form-item prop="alistId" label="引擎">
						<el-select v-model="editData.alistId" placeholder="请选择引擎" style="width: 100%;"
							no-data-text="暂无引擎,请前往引擎管理创建">
							<el-option v-for="item in alistList" :label="item.url" :value="item.id">
								<span
									style="float: left;margin-right: 16px;">{{item.url}}{{item.remark != null ? `[${item.remark}]` : ''}}</span>
								<span style="float: right; color: #7b9dad; font-size: 13px;">{{item.userName}}</span>
							</el-option>
						</el-select>
					</el-form-item>
					<el-form-item prop="srcPath" label="源目录">
						<div v-if="editData.alistId == null">请先选择引擎</div>
						<div v-else>
							{{editData.srcPath}}
							<el-button type="primary" size="mini" :style="`margin-left: ${editData.srcPath == '' ? 0 : 12}px;`"
								@click="selectPath(true)">{{editData.srcPath == '' ? '选择' : '更换'}}目录</el-button>
						</div>
					</el-form-item>
					<el-form-item prop="dstPath" label="目标目录">
						<div v-if="editData.alistId == null">请先选择引擎</div>
						<div v-else>
							<div style="display: flex;align-items: center;min-height: 42px;flex-wrap: wrap;">
								<div v-for="(item, index) in editData.dstPath"
									style="display: flex;align-items: center;margin: 4px 0;margin-right: 12px; flex-shrink: 0;">
									<div class="bg-1" style="border-radius: 3px; padding: 0 6px; line-height: 20px;margin-right: -4px;">
										{{item}}
									</div>
									<el-button style="border-radius: 0 3px 3px 0;" type="danger" size="mini"
										@click="delDstPath(index)">删除</el-button>
								</div>
								<el-button type="primary" size="mini"
									@click="selectPath(false)">{{editData.dstPath.length == 0 ? '选择' : '添加'}}目录</el-button>
							</div>
						</div>
					</el-form-item>
					<el-form-item prop="speed" label="同步速度">
						<el-select v-model="editData.speed" style="width: 100%;">
							<el-option label="标准" :value="0">
								<span style="float: left;margin-right: 16px;">标准</span>
								<span style="float: right; color: #7b9dad; font-size: 13px;">推荐使用</span>
							</el-option>
							<el-option label="快速" :value="1">
								<span style="float: left;margin-right: 16px;">快速</span>
								<span style="float: right; color: #7b9dad; font-size: 13px;">将使用Alist缓存扫描目标目录</span>
							</el-option>
						</el-select>
					</el-form-item>
					<el-form-item prop="method" label="同步方法">
						<el-select v-model="editData.method" style="width: 100%;">
							<el-option label="仅新增" :value="0">
								<span style="float: left;margin-right: 16px;">仅新增</span>
								<span style="float: right; color: #7b9dad; font-size: 13px;">仅新增目标目录没有的文件</span>
							</el-option>
							<el-option label="全同步" :value="1">
								<span style="float: left;margin-right: 16px;">全同步</span>
								<span style="float: right; color: #7b9dad; font-size: 13px;">目标目录比源目录多的文件将被删除</span>
							</el-option>
						</el-select>
					</el-form-item>
					<el-form-item prop="interval" label="同步间隔">
						<el-input v-model.number="editData.interval" placeholder="请输入同步间隔">
							<template slot="append">分钟</template>
						</el-input>
					</el-form-item>
				</el-form>
			</div>
			<span slot="footer" class="dialog-footer">
				<el-button @click="closeShow">取 消</el-button>
				<el-button type="primary" @click="submit" :loading="editLoading">确 定</el-button>
			</span>
		</el-dialog>
		<el-dialog :close-on-click-modal="false" :visible.sync="disableShow" :append-to-body="true" title="警告" width="460px"
			:before-close="closeDisableShow">
			<div style="color: #f56c6c;font-weight: bold;text-align: center;font-size: 20px;">
				{{disableIsDel ? '此操作不可逆，将永久删除该作业' : '将禁用任务'}}，确认吗？
			</div>
			<div style="display: flex;margin-top: 24px; align-items: center;justify-content: center;">
				<div style="margin-right: 6px;">是否取消执行中的任务（如有，不保证成功）</div>
				<el-switch v-model="disableCu.cancel">
				</el-switch>
			</div>
			<span slot="footer" class="dialog-footer">
				<el-button @click="closeDisableShow">取 消</el-button>
				<el-button type="primary" @click="submitDisable" :loading="editLoading">确 定</el-button>
			</span>
		</el-dialog>
		<pathSelect v-if="editData" :alistId="editData.alistId" ref="pathSelect" @submit="submitPath"></pathSelect>
	</div>
</template>

<script>
	import {
		jobGetJob,
		jobPut,
		jobDelete,
		jobPost,
		alistGet
	} from "@/api/job";
	import pathSelect from './components/pathSelect.vue';
	export default {
		name: 'Home',
		components: {
			pathSelect
		},
		data() {
			return {
				jobData: {
					dataList: [],
					conut: 0
				},
				params: {
					pageSize: 10,
					pageNum: 1
				},
				alistList: [],
				cuIsSrc: false,
				loading: false,
				btnLoading: false,
				editLoading: false,
				editData: null,
				editShow: false,
				disableShow: false,
				disableIsDel: false,
				disableCu: {
					id: null,
					pause: true,
					cancel: false
				},
				addRule: {
					srcPath: [{
						required: true,
						message: '请选择来源目录',
						trgger: 'change'
					}],
					dstPath: [{
						type: 'array',
						required: true,
						message: '请选择目标目录',
						trgger: 'change'
					}],
					alistId: [{
						type: 'number',
						required: true,
						message: '请选择引擎',
						trgger: 'change'
					}],
					interval: [{
						type: 'number',
						required: true,
						message: '请输入同步间隔',
						trgger: 'blur'
					}],
				}
			};
		},
		created() {
			this.getJobList();
		},
		beforeDestroy() {},
		methods: {
			getJobList() {
				this.loading = true;
				jobGetJob(this.params).then(res => {
					this.loading = false;
					this.jobData = res.data;
				}).catch(err => {
					this.loading = false;
				})
			},
			selectPath(isSrc) {
				this.cuIsSrc = isSrc;
				this.$refs.pathSelect.show();
			},
			getAlistList() {
				alistGet().then(res => {
					this.alistList = res.data;
				})
			},
			putJob(jobId, pause = null) {
				this.btnLoading = true;
				jobPut({
					id: jobId,
					pause: pause
				}).then(res => {
					this.btnLoading = false;
					this.$message({
						message: res.msg,
						type: 'success'
					});
					this.getJobList();
				}).catch(err => {
					this.btnLoading = false;
				})
			},
			disableJobShow(row, disableIsDel) {
				this.disableIsDel = disableIsDel;
				this.disableCu.id = row.id;
				this.disableShow = true;
			},
			editJobShow(row) {
				if (row.enable) {
					this.$message.error("禁用作业后才能编辑");
					return
				}
				if (this.alistList.length == 0) {
					this.getAlistList();
				}
				this.editData = JSON.parse(JSON.stringify(row));
				this.editData.dstPath = this.editData.dstPath.split(':');
				this.editShow = true;
			},
			addShow() {
				if (this.alistList.length == 0) {
					this.getAlistList();
				}
				this.editData = {
					enable: 1,
					srcPath: '',
					dstPath: [],
					alistId: null,
					speed: 0,
					method: 0,
					interval: 1440
				}
				this.editShow = true;
			},
			closeShow() {
				this.editShow = false;
			},
			closeDisableShow() {
				this.disableShow = false;
				this.disableCu = {
					id: null,
					pause: true,
					cancel: false
				};
			},
			delDstPath(index) {
				this.editData.dstPath.splice(index, 1);
			},
			submit() {
				this.$refs.jobRule.validate((valid) => {
					if (valid) {
						this.editLoading = true;
						let postData = JSON.parse(JSON.stringify(this.editData));
						postData.dstPath = postData.dstPath.join(':');
						jobPost(postData).then(res => {
							this.editLoading = false;
							this.$message({
								message: res.msg,
								type: 'success'
							});
							this.closeShow();
							this.getJobList();
						}).catch(err => {
							this.editLoading = false;
						})
					}
				})
			},
			submitDisable() {
				this.editLoading = true;
				if (this.disableIsDel) {
					jobDelete(this.disableCu).then(res => {
						this.editLoading = false;
						this.$message({
							message: res.msg,
							type: 'success'
						});
						this.getJobList();
						this.closeDisableShow();
					}).catch(err => {
						this.editLoading = false;
					})
				} else {
					jobPut(this.disableCu).then(res => {
						this.editLoading = false;
						this.$message({
							message: res.msg,
							type: 'success'
						});
						this.getJobList();
						this.closeDisableShow();
					}).catch(err => {
						this.editLoading = false;
					})
				}
			},
			submitPath(path) {
				if (this.cuIsSrc) {
					this.editData.srcPath = path;
				} else {
					if (this.editData.dstPath.includes(path)) {
						this.$message({
							message: '该目录已存在',
							type: 'error'
						});
					} else {
						this.editData.dstPath.push(path);
					}
				}
			},
			detail(jobId) {
				this.$router.push({
					path: '/home/task',
					query: {
						jobId
					}
				})
			},
			handleSizeChange(val) {
				this.params.pageSize = val;
				this.getJobList();
			},
			handleCurrentChange(val) {
				this.params.pageNum = val;
				this.getJobList();
			}
		}
	}
</script>

<style lang="scss" scoped>
	.home {
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

		.pathList {
			display: flex;
			flex-wrap: wrap;
			flex-shrink: 0;

			.pathBox {
				padding: 4px 10px;
				margin: 2px 0;
				margin-right: 6px;
				border-radius: 3px;
			}

			.pathBox:last-child {
				margin-right: 0;
			}
		}

		.page {
			margin-top: 24px;
			display: flex;
			justify-content: right;
		}
	}
</style>