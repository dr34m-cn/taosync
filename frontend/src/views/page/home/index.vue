<template>
	<div class="home">
		<div class="top-box">
			<div class="top-box-left">
				<el-button type="success" icon="el-icon-plus" @click="addShow"
					style="margin-right: 58px;" size="small">新建作业</el-button>
				<el-button @click="runAllJob" v-if="jobData.dataList.length > 1" icon="el-icon-caret-right"
					:loading="btnLoading" type="primary">执行全部</el-button>
			</div>
			<div class="top-box-title">作业管理</div>
			<menuRefresh :autoRefresh="false" :freshInterval="5273" :loading="loading" @getData="getJobList">
			</menuRefresh>
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
								{{props.row.method == 0 ? '仅新增' : (props.row.method == 1 ? '全同步': '移动模式')}}
							</div>
						</div>
						<div class="form-box-item">
							<div class="form-box-item-label">
								同步速度
							</div>
							<div class="form-box-item-value">
								{{props.row.speed == 0 ? '标准' : (props.row.speed == 1 ? '快速' : '低速')}}
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
								排除项规则
							</div>
							<div class="form-box-item-value">
								<span v-if="props.row.exclude == null">-</span>
								<template v-else>
									<span class="exclude-item bg-3" v-for="item in props.row.exclude.split(':')">
										{{item}}
									</span>
								</template>
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
								<template v-if="props.row.isCron != 2">
									<el-button type="warning" :loading="btnLoading" size="mini" v-if="props.row.enable"
										@click="disableJobShow(props.row, false)">禁用</el-button>
									<el-button type="success" :loading="btnLoading" size="mini" v-else
										@click="putJob(props.row, false)">启用</el-button>
								</template>
								<el-button type="danger" :loading="btnLoading" size="mini"
									@click="disableJobShow(props.row, true)">删除</el-button>
								<el-button type="primary" :loading="btnLoading" size="mini"
									@click="editJobShow(props.row)">编辑</el-button>
								<!-- <el-button type="success" :loading="btnLoading" size="small" @click="putJob(props.row)">手动执行</el-button> -->
							</div>
						</div>
					</div>
				</template>
			</el-table-column>
			<el-table-column prop="remark" label="名称" width="120">
				<template slot-scope="scope">
					{{scope.row.remark || '--'}}
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
			<el-table-column label="操作" align="center" width="200">
				<template slot-scope="scope">
					<el-button icon="el-icon-caret-right" type="primary" @click="putJob(scope.row)"
						:loading="btnLoading" size="mini">手动执行</el-button>
					<el-button icon="el-icon-view" type="success" @click="detail(scope.row.id)" :loading="btnLoading"
						size="mini">详情</el-button>
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
						<el-form-item prop="remark" label="作业名称">
							<div class="label_width">
								<el-input v-model="editData.remark" placeholder="用来标识你的作业，选填"></el-input>
							</div>
						</el-form-item>
						<el-form-item prop="alistId" label="引擎">
							<el-select v-model="editData.alistId" placeholder="请选择引擎" class="label_width label_width_2"
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
								<div class="label-list-box">
									<div v-for="(item, index) in editData.dstPath" class="label-list-item">
										<div class="bg-1 label-list-item-left">
											{{item}}
										</div>
										<el-button type="danger" size="mini" @click="delDstPath(index)">删除</el-button>
									</div>
									<el-button type="primary" size="mini"
										@click="selectPath(false)">{{editData.dstPath.length == 0 ? '选择' : '添加'}}目录</el-button>
								</div>
							</div>
						</el-form-item>
						<el-form-item prop="exclude" label="排除项语法">
							<div class="label_width">类gitignore<br />
								<span @click="toIgnore" class="to-link">
									点击查看排除项简易教程
								</span>
							</div>
						</el-form-item>
						<el-form-item prop="exclude" label="排除项规则">
							<div class="label_width">
								<div class="label-list-box">
									<el-input v-model="excludeTmp" placeholder="输入后点添加才生效">
										<el-button slot="append" @click="addExclude">添加</el-button>
									</el-input>
									<div v-for="(item, index) in editData.exclude" class="label-list-item">
										<div class="bg-3 label-list-item-left">
											{{item}}
										</div>
										<el-button type="danger" size="mini" @click="delExclude(index)">删除</el-button>
									</div>
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
								<el-option label="低速" :value="2">
									<span style="float: left;margin-right: 16px;">低速</span>
									<span style="float: right; color: #7b9dad; font-size: 13px;">频繁被网盘限制可尝试这个选项</span>
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
								<el-option label="移动模式" :value="2">
									<span style="float: left;margin-right: 16px;">移动模式</span>
									<span style="float: right; color: #7b9dad; font-size: 13px;">同步完成后删除源目录所有文件</span>
								</el-option>
							</el-select>
						</el-form-item>
						<span v-if="editData.method == 2"
							style="margin-top: -12px;margin-left: 410px;margin-bottom: 18px;color: #f56c6c;font-weight: bold;">移动模式存在风险，可能导致文件丢失（因为会删除源目录文件），该方法应仅用于不重要的文件或有多重备份的文件！希望你知道自己在做什么！</span>
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
							<el-form-item prop="isCron" label="简易教程">
								<div class="label_width">
									<span @click="toCron" class="to-link">
										点击查看cron简易教程
									</span>
								</div>

							</el-form-item>
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
	import menuRefresh from './components/menuRefresh';
	export default {
		name: 'Home',
		components: {
			pathSelect,
			menuRefresh
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
				excludeTmp: '',
				editShow: false,
				disableShow: false,
				disableIsDel: false,
				disableCu: {
					id: null,
					pause: true
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
			runAllJob() {
				this.$confirm("确认执行所有未禁用的作业吗？", '提示', {
					confirmButtonText: '确定',
					cancelButtonText: '取消',
					type: 'warning'
				}).then(() => {
					this.btnLoading = true;
					jobPut({
						pause: null
					}).then(res => {
						this.btnLoading = false;
						this.$message({
							message: res.msg,
							type: 'success'
						});
					}).catch(err => {
						this.btnLoading = false;
					})
				})
			},
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
			toIgnore() {
				window.open('https://blog.ctftools.com/2024/09/newpost-60/', '_blank');
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
				this.excludeTmp = '';
				this.editData = JSON.parse(JSON.stringify(row));
				this.editData.dstPath = this.editData.dstPath.split(':');
				if (this.editData.exclude) {
					this.editData.exclude = this.editData.exclude.split(':');
				} else {
					this.editData.exclude = [];
				}
				this.editShow = true;
			},
			addShow() {
				if (this.alistList.length == 0) {
					this.getAlistList();
				}
				let editData = {
					enable: 1,
					remark: '',
					srcPath: '',
					dstPath: [],
					alistId: null,
					speed: 0,
					method: 0,
					interval: 1440,
					isCron: 0,
					exclude: []
				}
				this.cronList.forEach(item => {
					editData[item.label] = null;
				})
				this.editData = editData;
				this.excludeTmp = '';
				this.editShow = true;
			},
			closeShow() {
				this.editShow = false;
			},
			closeDisableShow() {
				this.disableShow = false;
				this.disableCu = {
					id: null,
					pause: true
				};
			},
			addExclude() {
				if (this.excludeTmp != '') {
					this.editData.exclude.push(this.excludeTmp);
				}
				this.excludeTmp = '';
			},
			delExclude(index) {
				this.editData.exclude.splice(index, 1);
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
						postData.exclude = postData.exclude.join(':');
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

			.top-box-left {
				display: flex;
				align-items: center;
			}
		}

		.pathList {
			display: flex;
			flex-wrap: wrap;
			flex-shrink: 0;

			.pathBox {
				font-size: 14px;
				padding: 2px 6px;
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

		.label-list-box {
			display: flex;
			align-items: center;
			flex-wrap: wrap;
			min-height: 42px;

			.label-list-item {
				display: flex;
				align-items: center;
				margin: 4px 0;
				margin-right: 12px;
				flex-shrink: 0;

				.label-list-item-left {
					border-radius: 3px;
					padding: 0 6px;
					line-height: 20px;
					margin-right: -4px;
				}

				.el-button {
					border-radius: 0 3px 3px 0;
				}
			}
		}

		.to-link {
			color: #409eff;
			text-decoration: underline;
			cursor: pointer;
		}
	}

	.label_width_2 {
		width: 600px;
	}

	.exclude-item {
		margin-right: 6px;
		padding: 0 2px;
		border-radius: 3px;
	}

	.exclude-item:last-child {
		margin-right: 0;
	}
</style>