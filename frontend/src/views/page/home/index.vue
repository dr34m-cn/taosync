<template>
	<div class="home">
		<div class="top-box">
			<el-button type="success" icon="el-icon-plus" @click="addShow">新建作业</el-button>
			<div class="top-box-title">作业管理</div>
			<el-button :loading="loading" type="primary" icon="el-icon-refresh" circle @click="getJobList"></el-button>
		</div>
		<el-table :data="jobData.dataList" class="table-data" height="calc(100% - 117px)" v-loading="loading">
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
								调用方式
							</div>
							<div class="form-box-item-value">
								{{props.row.isCron == 0 ? '间隔' : (props.row.isCron == 1 ? 'cron' : '仅手动')}}
							</div>
						</div>
						<div class="form-box-item" v-if="props.row.isCron == 0">
							<div class="form-box-item-label">
								同步间隔
							</div>
							<div class="form-box-item-value">
								{{props.row.interval}} 分钟
							</div>
						</div>
						<template v-else-if="props.row.isCron == 1">
							<div class="form-box-item" v-for="item in cronList">
								<div class="form-box-item-label">
									{{item.label}}
								</div>
								<div class="form-box-item-value">
									{{props.row[item.label] || '-'}}
								</div>
							</div>
						</template>
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
								<template v-if="props.row.isCron != 2">
									<el-button type="warning" :loading="btnLoading" size="small" v-if="props.row.enable"
										@click="disableJobShow(props.row, false)">禁用</el-button>
									<el-button type="success" :loading="btnLoading" size="small" v-else
										@click="putJob(props.row, false)">启用</el-button>
								</template>
								<el-button type="danger" :loading="btnLoading" size="small"
									@click="disableJobShow(props.row, true)">删除</el-button>
								<el-button type="primary" :loading="btnLoading" size="small"
									@click="editJobShow(props.row)">编辑</el-button>
								<el-button type="success" :loading="btnLoading" size="small"
									@click="putJob(props.row)">手动执行</el-button>
							</div>
						</div>
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="enable" label="状态" width="80">
				<template slot-scope="scope">
					<div :class="`bg-status bg-${scope.row.enable ? '2' : '7'}`" style="width: 50px;">
						{{scope.row.enable ? '启用' : '禁用'}}
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="srcPath" label="来源目录" min-width="50">
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
			<el-table-column label="操作" align="center" width="100">
				<template slot-scope="scope">
					<el-button type="primary" @click="detail(scope.row.id)" :loading="btnLoading"
						size="small">详情</el-button>
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
			:title="`${editData && editData.id != null ? '编辑' : '新增'}作业`" width="760px" :before-close="closeShow">
			<div class="elform-box">
				<el-form :model="editData" :rules="addRule" ref="jobRule" v-if="editShow" label-width="120px">
					<div style="display: flex;flex-wrap: wrap;">
						<el-form-item prop="enable" label="是否启用">
							<div class="label_width">
								<el-switch v-model="editData.enable" :active-value="1" :inactive-value="0"
									v-if="editData.isCron != 2">
								</el-switch>
								<span v-else>启用</span>
							</div>
						</el-form-item>
						<el-form-item prop="alistId" label="引擎">
							<el-select v-model="editData.alistId" placeholder="请选择引擎" class="label_width"
								no-data-text="暂无引擎,请前往引擎管理创建">
								<el-option v-for="item in alistList" :label="item.url" :value="item.id">
									<span
										style="float: left;margin-right: 16px;">{{item.url}}{{item.remark != null ? `[${item.remark}]` : ''}}</span>
									<span
										style="float: right; color: #7b9dad; font-size: 13px;">{{item.userName}}</span>
								</el-option>
							</el-select>
						</el-form-item>
						<el-form-item prop="srcPath" label="源目录">
							<div v-if="editData.alistId == null" class="label_width">请先选择引擎</div>
							<div v-else class="label_width">
								{{editData.srcPath}}
								<el-button type="primary" size="mini"
									:style="`margin-left: ${editData.srcPath == '' ? 0 : 12}px;`"
									@click="selectPath(true)">{{editData.srcPath == '' ? '选择' : '更换'}}目录</el-button>
							</div>
						</el-form-item>
						<el-form-item prop="dstPath" label="目标目录">
							<div v-if="editData.alistId == null" class="label_width">请先选择引擎</div>
							<div v-else class="label_width">
								<div style="display: flex;align-items: center;min-height: 42px;flex-wrap: wrap;">
									<div v-for="(item, index) in editData.dstPath"
										style="display: flex;align-items: center;margin: 4px 0;margin-right: 12px; flex-shrink: 0;">
										<div class="bg-1"
											style="border-radius: 3px; padding: 0 6px; line-height: 20px;margin-right: -4px;">
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
							<el-select v-model="editData.speed" class="label_width">
								<el-option label="标准" :value="0">
									<span style="float: left;margin-right: 16px;">标准</span>
									<span style="float: right; color: #7b9dad; font-size: 13px;">不会选就用这个</span>
								</el-option>
								<el-option label="快速" :value="1">
									<span style="float: left;margin-right: 16px;">快速</span>
									<span style="float: right; color: #7b9dad; font-size: 13px;">将使用Alist缓存扫描目标目录</span>
								</el-option>
							</el-select>
						</el-form-item>
						<el-form-item prop="method" label="同步方法">
							<el-select v-model="editData.method" class="label_width">
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
						<el-form-item prop="isCron" label="调用方式">
							<el-select v-model="editData.isCron" class="label_width">
								<el-option label="间隔" :value="0">
									<span style="float: left;margin-right: 16px;">间隔</span>
									<span style="float: right; color: #7b9dad; font-size: 13px;">每n分钟同步一次</span>
								</el-option>
								<el-option label="cron" :value="1">
									<span style="float: left;margin-right: 16px;">cron</span>
									<span style="float: right; color: #7b9dad; font-size: 13px;">推荐使用，有教程</span>
								</el-option>
								<el-option label="仅手动" :value="2">
									<span style="float: left;margin-right: 16px;">仅手动</span>
									<span style="float: right; color: #7b9dad; font-size: 13px;">不自动调用</span>
								</el-option>
							</el-select>
						</el-form-item>
						<template v-if="editData.isCron == 0">
							<el-form-item prop="interval" label="同步间隔">
								<el-input v-model.number="editData.interval" placeholder="请输入同步间隔" class="label_width">
									<template slot="append">分钟</template>
								</el-input>
							</el-form-item>
							<span style="margin-left: 100px;">间隔方式不会立即调用，如有需要，可在创建后立即手动调用</span>
						</template>
						<template v-else-if="editData.isCron == 1">
							<div class="el-form-item" style="display: flex;align-items: center;">
								<div class="el-form-item__label" style="width: 120px;">cron教程</div>
								<span @click="toCron"
									style="color: #409eff;margin-left: 16px;text-decoration: underline;cursor: pointer;">
									简易教程
								</span>
							</div>
							<el-form-item v-for="item in cronList" :prop="item.label" :label="item.label">
								<el-input v-model="editData[item.label]" :placeholder="item.palce" class="label_width">
								</el-input>
							</el-form-item>
						</template>
					</div>
				</el-form>
			</div>
			<span slot="footer" class="dialog-footer">
				<el-button @click="closeShow">取 消</el-button>
				<el-button type="primary" @click="submit" :loading="editLoading">确 定</el-button>
			</span>
		</el-dialog>
		<el-dialog :close-on-click-modal="false" :visible.sync="disableShow" :append-to-body="true" title="警告"
			width="460px" :before-close="closeDisableShow">
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
				cronList: [{
					label: 'year',
					palce: '2024'
				}, {
					label: 'month',
					palce: '1-12'
				}, {
					label: 'day',
					palce: '1-31'
				}, {
					label: 'week',
					palce: '1-53'
				}, {
					label: 'day_of_week',
					palce: '0-6 or mon,tue,wed,thu,fri,sat,sun'
				}, {
					label: 'hour',
					palce: '0-23'
				}, {
					label: 'minute',
					palce: '0-59'
				}, {
					label: 'second',
					palce: '0-59'
				}, {
					label: 'start_date',
					palce: '2000-01-01'
				}, {
					label: 'end_date',
					palce: '2040-12-31'
				}],
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
					}]
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
			toCron() {
				window.open('https://blog.ctftools.com/2024/08/newpost-58/', '_blank');
			},
			putJob(row, pause = null) {
				if (row.enable != 1 && pause !== false) {
					this.$message.error("如需手动执行，请先启用作业");
					return
				}
				this.btnLoading = true;
				jobPut({
					id: row.id,
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
				if (row.enable && row.isCron != 2) {
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
				let editData = {
					enable: 1,
					srcPath: '',
					dstPath: [],
					alistId: null,
					speed: 0,
					method: 0,
					interval: 1440,
					isCron: 1
				}
				this.cronList.forEach(item => {
					editData[item.label] = null;
				})
				this.editData = editData;
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
						let postData = JSON.parse(JSON.stringify(this.editData));
						for (let i in postData) {
							if (postData[i] === '') {
								postData[i] = null;
							}
						}
						if (postData.isCron == 0 && postData.interval == null) {
							this.$message.error("选择间隔方式时，间隔必填");
							return
						}
						if (postData.isCron == 1) {
							let flag = 0;
							this.cronList.forEach(item => {
								if (postData[item.label] != null) {
									flag += 1;
								}
							})
							if (flag == 0) {
								this.$message.error("选择cron方式时，至少有一项不能为空");
								return
							}
						}
						postData.dstPath = postData.dstPath.join(':');
						this.editLoading = true;
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

<style lang="scss">
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

	.label_width {
		width: 240px;
	}
</style>