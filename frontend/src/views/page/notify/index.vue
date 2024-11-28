<template>
	<div class="notify" v-loading="loading">
		<div class="card-item" v-for="item in dataList">
			<div class="card-item-top">
				<el-image :src="`/notify/${item.method}.png`" fit="contain" style="width: 60px;height: 60px;"></el-image>
				<div style="margin-left: 12px;">
					<div class="card-item-user">{{item.method | notifyMethodFilter}}</div>
					<div :class="`card-item-enable enable-${item.enable == 1 ? 'enable' : 'disable'}`">
						{{item.enable == 1 ? '已启用' : '已禁用'}}
					</div>
				</div>
			</div>
			<div class="card-item-bottom">
				<el-button size="small" type="primary" @click="editShowDialog(item)">编辑</el-button>
				<el-button size="small" type="success" v-if="item.enable == 0" @click="enableNotify(item.id, 1)">启用</el-button>
				<el-button size="small" type="warning" v-else @click="enableNotify(item.id, 0)">禁用</el-button>
				<el-button size="small" type="primary" :loading="tstLoading" @click="tstCu(item)">测试</el-button>
				<el-button size="small" type="danger" @click="delCu(item.id)">删除</el-button>
			</div>
		</div>
		<div class="card-item card-add" @click="addShow" v-if="!loading">
			<template v-if="dataList.length == 0">
				暂无通知配置，请<span style="color: #409eff;">新增</span>
			</template>
			<span v-else>新增</span>
		</div>
		<el-dialog :close-on-click-modal="false" top="6vh" :visible.sync="editShow" :title="editFlag ? '编辑' : '新增'"
			width="680px" :before-close="closeShow" :append-to-body="true">
			<div class="elform-box">
				<el-form :model="editData" :rules="editRule[editData.method]" ref="addRule" v-if="editShow" label-width="100px">
					<el-form-item prop="enable" label="是否启用">
						<el-switch v-model="editData.enable" :active-value="1" :inactive-value="0">
						</el-switch>
					</el-form-item>
					<el-form-item prop="method" label="方式">
						<el-select v-model="editData.method" @change="methodChange" style="width: 100%;">
							<el-option :key="meItem - 1" :value="meItem - 1" :label="meItem - 1 | notifyMethodFilter"
								v-for="meItem in 3"></el-option>
							<!-- <el-option :key="1" :value="1" label="server酱"></el-option>
							<el-option :key="2" :value="2" label="钉钉机器人"></el-option> -->
						</el-select>
					</el-form-item>
					<template v-if="editData.method == 0">
						<el-form-item prop="params.url" label="请求地址">
							<el-input v-model="editData.params.url" placeholder="请输入请求地址"></el-input>
						</el-form-item>
						<el-form-item prop="params.method" label="请求方法">
							<el-select v-model="editData.params.method" style="width: 100%;">
								<el-option key="POST" value="POST" label="POST"></el-option>
								<el-option key="PUT" value="PUT" label="PUT"></el-option>
								<el-option key="GET" value="GET" label="GET"></el-option>
							</el-select>
						</el-form-item>
						<el-form-item v-if="editData.params.method != 'GET'" prop="params.contentType" label="请求体类型">
							<el-select v-model="editData.params.contentType" style="width: 100%;">
								<el-option key="application/json" value="application/json" label="application/json"></el-option>
								<el-option key="application/x-www-form-urlencoded" value="application/x-www-form-urlencoded"
									label="application/x-www-form-urlencoded"></el-option>
							</el-select>
						</el-form-item>
						<el-form-item prop="params.titleName" label="标题参数名">
							<el-input v-model="editData.params.titleName" placeholder="请输入标题参数名"></el-input>
						</el-form-item>
						<el-form-item prop="params.needContent" label="是否需要内容">
							<el-select v-model="editData.params.needContent" style="width: 100%;">
								<el-option :key="true" :value="true" label="需要"></el-option>
								<el-option :key="false" :value="false" label="不需要"></el-option>
							</el-select>
						</el-form-item>
						<el-form-item prop="params.contentName" v-if="editData.params.needContent" label="内容参数名">
							<el-input v-model="editData.params.contentName" placeholder="请输入内容参数名"></el-input>
						</el-form-item>
					</template>
					<template v-else-if="editData.method == 1">
						<div class="tip-box">同时支持 <a href="https://sct.ftqq.com/" target="_blank">Server酱ᵀ</a>(免费5次/天)
							与 <a href="https://sc3.ft07.com/" target="_blank">Server酱³</a>(公测不限次)</div>
						<el-form-item prop="params.sendKey" label="SendKey">
							<el-input v-model="editData.params.sendKey" placeholder="请输入SendKey"></el-input>
						</el-form-item>
					</template>
					<template v-else-if="editData.method == 2">
						<div class="tip-box"><a
								href="https://open.dingtalk.com/document/orgapp/custom-bot-creation-and-installation"
								target="_blank">配置指南</a> 安全设置请采用[自定义关键字]，关键字内容为[TaoSync]，不含中括号</div>
						<el-form-item prop="params.url" label="WebHook">
							<el-input v-model="editData.params.url"
								placeholder="https://oapi.dingtalk.com/robot/send?access_token=xxxx"></el-input>
						</el-form-item>
					</template>
				</el-form>
			</div>
			<span slot="footer" class="dialog-footer">
				<el-button @click="closeShow">取 消</el-button>
				<el-button type="success" :loading="tstLoading" @click="tstCu()">测 试</el-button>
				<el-button type="primary" @click="submit" :loading="editLoading">确 定</el-button>
			</span>
		</el-dialog>
	</div>
</template>

<script>
	import {
		getNotifyList,
		delNotify,
		putEnableNotify,
		postAddNotify,
		putEditNotify
	} from '@/api/notify';
	export default {
		name: 'Notify',
		components: {},
		data() {
			return {
				dataList: [],
				loading: false,
				deleteLoading: false,
				editLoading: false,
				tstLoading: false,
				enableLoading: false,
				editData: null,
				editFlag: false,
				editShow: false,
				editRule: [{
					params: {
						url: [{
							type: 'string',
							required: true,
							message: '请输入地址'
						}],
						titleName: [{
							type: 'string',
							required: true,
							message: '请输入标题名'
						}],
						contentName: [{
							type: 'string',
							required: true,
							message: '请输入内容名'
						}]
					}
				}, {
					params: {
						sendKey: [{
							type: 'string',
							required: true,
							message: '请输入sendKey'
						}]
					}
				}, {
					params: {
						url: [{
							type: 'string',
							required: true,
							message: '请输入WebHook地址'
						}]
					}
				}]
			};
		},
		created() {
			this.getData();
		},
		beforeDestroy() {},
		methods: {
			getData() {
				this.loading = true;
				getNotifyList().then(res => {
					this.loading = false;
					this.dataList = res.data;
				}).catch(err => {
					this.loading = false;
				})
			},
			addShow() {
				this.editFlag = false;
				this.editData = {
					enable: 1,
					method: 1,
					params: {
						sendKey: ''
					}
				}
				this.editShow = true;
			},
			editShowDialog(row) {
				this.editData = JSON.parse(JSON.stringify(row));
				this.editData.params = JSON.parse(this.editData.params);
				this.editFlag = true;
				this.editShow = true;
			},
			methodChange(val) {
				if (val === 0) {
					this.editData.params = {
						url: '',
						method: 'POST',
						contentType: 'application/json',
						needContent: true,
						titleName: 'title',
						contentName: 'content'
					}
				} else if (val === 1) {
					this.editData.params = {
						sendKey: ''
					}
				} else if (val === 2) {
					this.editData.params = {
						url: ''
					}
				}
				this.$nextTick(() => {
					this.$refs.addRule.clearValidate();
				})
			},
			closeShow() {
				this.editShow = false;
			},
			enableNotify(notifyId, enable) {
				this.enableLoading = true;
				putEnableNotify(notifyId, enable).then(res => {
					this.enableLoading = false;
					this.$message({
						message: res.msg,
						type: 'success'
					});
					this.getData();
				}).catch(err => {
					this.enableLoading = false;
				})
			},
			submit() {
				this.$refs.addRule.validate((valid) => {
					if (valid) {
						let dt = JSON.parse(JSON.stringify(this.editData));
						dt.params = JSON.stringify(dt.params);
						this.editLoading = true;
						if (this.editFlag) {
							putEditNotify(dt).then(res => {
								this.editLoading = false;
								this.$message({
									message: res.msg,
									type: 'success'
								});
								this.closeShow();
								this.getData();
							}).catch(err => {
								this.editLoading = false;
							})
						} else {
							postAddNotify(dt).then(res => {
								this.editLoading = false;
								this.$message({
									message: res.msg,
									type: 'success'
								});
								this.closeShow();
								this.getData();
							}).catch(err => {
								this.editLoading = false;
							})
						}
					}
				})
			},
			tstCu(item = null) {
				if (item == null) {
					this.$refs.addRule.validate((valid) => {
						if (valid) {
							this.tstCuTrueDo(this.editData);
						}
					})
				} else {
					this.tstCuTrueDo(item);
				}
			},
			tstCuTrueDo(item) {
				this.tstLoading = true;
				let it = JSON.parse(JSON.stringify(item));
				if (typeof it.params === 'object' && it.params !== null) {
					it.params = JSON.stringify(it.params);
				}
				delete it.enable;
				postAddNotify(it).then(res => {
					this.tstLoading = false;
					this.$message({
						message: '测试消息已发送，请检查是否正确收到通知',
						type: 'success'
					});
				}).catch(err => {
					this.tstLoading = false;
				})
			},
			delCu(id) {
				this.$confirm("操作不可逆，将永久删除该通知配置，仍要删除吗？", '提示', {
					confirmButtonText: '确定',
					cancelButtonText: '取消',
					type: 'warning'
				}).then(() => {
					this.deleteLoading = true;
					delNotify(id).then(res => {
						this.deleteLoading = false;
						this.$message({
							message: res.msg,
							type: 'success'
						});
						this.getData();
					}).catch(err => {
						this.deleteLoading = false;
					})
				});
			}
		}
	}
</script>

<style lang="scss">
	.tip-box {
		margin: 0 0 20px 100px;
		color: #909bd4;

		a {
			color: #409eff;
		}

		a:hover {
			color: #66b1ff;
		}
	}

	.notify {
		box-sizing: border-box;
		padding: 8px;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(380px, 2fr));
		width: 100%;

		.card-item {
			background-color: #292b3c;
			border-radius: 5px;
			border: 1px solid;
			border-color: transparent;
			height: 110px;
			margin: 8px;
			padding: 6px;

			.card-item-top {
				display: flex;
				align-items: center;
				justify-content: center;

				.card-item-user {
					font-size: 18px;
					display: flex;
				}

				.card-item-enable {
					margin-top: 6px;
					font-weight: bold;
				}

				.enable-enable {
					color: #67c23a;
				}

				.enable-disable {
					color: #f56c6c;
				}
			}

			.card-item-bottom {
				display: flex;
				align-items: center;
				justify-content: center;
				margin-top: 12px;
			}
		}

		.card-add {
			font-size: 32px;
			cursor: pointer;
			display: flex;
			justify-content: center;
			align-items: center;
		}

		.card-item:hover {
			border-color: #409eff;
			background-color: #3d415a;
		}

		.card-add:hover {
			font-size: 32px;
			color: #409eff;
			font-weight: bold;
		}
	}
</style>