<template>
	<div class="engine">
		<div class="loading-box content-none-data" v-loading="true" v-if="getLoading">加载中</div>
		<div v-else class="card-box">
			<div class="card-item" v-for="item in alistList">
				<div class="card-item-top">
					<el-image src="/alist.svg" fit="contain" style="width: 60px;height: 60px;"></el-image>
					<div style="margin-left: 12px;">
						<div class="card-item-user">{{item.userName}}
							<div class="card-item-remark" v-if="item.remark != null">[{{item.remark}}]</div>
						</div>
						<div class="card-item-url">{{item.url}}</div>
					</div>
				</div>
				<div class="card-item-bottom">
					<el-button size="small" type="primary" @click="editShowDialog(item)">编辑</el-button>
					<el-button size="small" type="danger" @click="delAlist(item.id)">删除</el-button>
				</div>
			</div>
			<div class="card-item card-add" @click="addShow" v-if="!getLoading">
				<template v-if="alistList.length == 0">
					暂无引擎，请<span style="color: #409eff;">新增</span>
				</template>
				<span v-else>新增</span>
			</div>
			<el-dialog :close-on-click-modal="false" :visible.sync="editShow" :title="editFlag ? '编辑' : '新增'" width="600px"
				:before-close="closeShow" :append-to-body="true">
				<div class="elform-box">
					<el-form :model="editData" :rules="editFlag ? editRule : addRule" ref="addRule" v-if="editShow"
						label-width="66px">
						<el-form-item prop="url" label="地址">
							<el-input v-model="editData.url" placeholder="请输入地址，如http://127.0.0.1:5244"></el-input>
						</el-form-item>
						<el-form-item prop="remark" label="备注">
							<el-input v-model="editData.remark" placeholder="备注方便你标识引擎，非必填"></el-input>
						</el-form-item>
						<el-form-item prop="token" label="令牌">
							<el-input v-model="editData.token" show-password
								:placeholder="`请输入令牌，${editFlag ? '留空表示不修改' : '请到AList管理-设置-其他中复制，保存后不要重置令牌'}`"
								@keyup.enter.native="submit"></el-input>
						</el-form-item>
					</el-form>
				</div>
				<span slot="footer" class="dialog-footer">
					<el-button @click="closeShow">取 消</el-button>
					<el-button type="primary" @click="submit" :loading="editLoading">确 定</el-button>
				</span>
			</el-dialog>
		</div>
	</div>
</template>

<script>
	import {
		alistGet,
		alistPost,
		alistPut,
		alistDelete
	} from "@/api/job";
	export default {
		name: 'Engine',
		components: {},
		data() {
			return {
				alistList: [],
				getLoading: false,
				deleteLoading: false,
				editLoading: false,
				editData: null,
				editFlag: false,
				editShow: false,
				editRule: {
					url: [{
						required: true,
						message: '请输入地址',
						trgger: 'blur'
					}]
				},
				addRule: {
					url: [{
						required: true,
						message: '请输入地址',
						trgger: 'blur'
					}],
					token: [{
						required: true,
						message: '请输入令牌，请到AList管理-设置-其他中复制，保存后不要重置令牌否则令牌失效',
						trgger: 'blur'
					}]
				}
			};
		},
		created() {
			this.getAlistList();
		},
		beforeDestroy() {},
		methods: {
			getAlistList() {
				this.getLoading = true;
				alistGet().then(res => {
					this.getLoading = false;
					this.alistList = res.data;
				}).catch(err => {
					this.getLoading = false;
				})
			},
			addShow() {
				this.editFlag = false;
				this.editData = {
					remark: '',
					url: '',
					token: ''
				}
				this.editShow = true;
			},
			editShowDialog(row) {
				this.editData = {
					...row,
					token: ''
				};
				this.editFlag = true;
				this.editShow = true;
			},
			closeShow() {
				this.editShow = false;
			},
			submit() {
				this.$refs.addRule.validate((valid) => {
					if (valid) {
						this.editData.url = this.ensureHttpPrefix(this.editData.ur);
						this.editLoading = true;
						if (this.editFlag) {
							alistPut(this.editData).then(res => {
								this.editLoading = false;
								this.$message({
									message: res.msg,
									type: 'success'
								});
								this.closeShow();
								this.getAlistList();
							}).catch(err => {
								this.editLoading = false;
							})
						} else {
							alistPost(this.editData).then(res => {
								this.editLoading = false;
								this.$message({
									message: res.msg,
									type: 'success'
								});
								this.closeShow();
								this.getAlistList();
							}).catch(err => {
								this.editLoading = false;
							})
						}
					}
				})
			},
			delAlist(alistId) {
				this.$confirm("操作不可逆，将永久删除该引擎，请确认没有作业使用该引擎，否则会导致错误，仍要删除吗？", '提示', {
					confirmButtonText: '确定',
					cancelButtonText: '取消',
					type: 'warning'
				}).then(() => {
					this.deleteLoading = true;
					alistDelete(alistId).then(res => {
						this.deleteLoading = false;
						this.$message({
							message: res.msg,
							type: 'success'
						});
						this.getAlistList();
					}).catch(err => {
						this.deleteLoading = false;
					})
				});
			},
			ensureHttpPrefix(url) {
				if (!/^https?:\/\//i.test(url)) {
					if (url.startsWith('//')) {
						return 'http:' + url;
					}
					return 'http://' + url;
				}
				return url;
			}
		}
	}
</script>

<style lang="scss" scoped>
	.engine {
		box-sizing: border-box;
		width: 100%;
		height: 100%;

		.loading-box {
			box-sizing: border-box;
			width: 100%;
			height: 100%;
		}

		.card-box {
			box-sizing: border-box;
			padding: 8px;
			display: grid;
			grid-template-columns: repeat(auto-fill, minmax(340px, 2fr));
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

						.card-item-remark {
							margin-left: 6px;
							color: #d6d12f;
							max-width: 120px;
							white-space: nowrap;
							overflow: hidden;
							text-overflow: ellipsis;
						}
					}

					.card-item-url {
						margin-top: 8px;
						font-size: 12px;
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


	}
</style>