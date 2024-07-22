<template>
	<div class="user">
		<div class="user-info">
			<template v-if="vuex_userInfo">
				<div class="item">
					<div class="label">用户名</div>
					<div class="value">{{vuex_userInfo.userName}}</div>
				</div>
				<div class="item">
					<div class="label">创建时间</div>
					<div class="value">{{vuex_userInfo.createTime | timeStampFilter}}</div>
				</div>
				<el-form :model="resetForm" :rules="rules" ref="resetForm" label-width="0">
					<el-form-item prop="oldPasswd">
						<el-input class="input" placeholder="请输入旧密码" show-password v-model="resetForm.oldPasswd"></el-input>
					</el-form-item>
					<el-form-item prop="passwd">
						<el-input placeholder="请输入新密码" show-password v-model="resetForm.passwd" show-password></el-input>
					</el-form-item>
					<el-form-item prop="passwd2">
						<el-input placeholder="确认新密码" show-password v-model="resetForm.passwd2" show-password
							@keyup.enter.native="resetPasswd"></el-input>
					</el-form-item>
				</el-form>
				<el-button type="primary" :loading="loading" @click="resetPasswd">修改密码</el-button>
			</template>
		</div>
		<div class="version">TaoSync 版本：__version_placeholder__</div>
	</div>
</template>

<script>
	import {
		resetPwd
	} from "@/api/user";
	export default {
		name: 'User',
		data() {
			var validatePass2 = (rule, value, callback) => {
				if (value == '' || value == null) {
					callback(new Error('请再次输入新密码'));
				} else if (value !== this.resetForm.passwd) {
					callback(new Error('两次输入密码不一致!'));
				} else {
					callback();
				}
			};
			return {
				resetForm: {
					oldPasswd: null,
					passwd: null,
					passwd2: null
				},
				loading: false,
				rules: {
					oldPasswd: [{
						required: true,
						message: '请输入旧密码',
						trigger: 'blur'
					}],
					passwd: [{
						required: true,
						message: '请输入新密码',
						trigger: 'blur'
					}],
					passwd2: [{
						validator: validatePass2,
						trigger: 'blur'
					}]
				}
			};
		},
		created() {},
		methods: {
			resetPasswd() {
				this.$refs.resetForm.validate((valid) => {
					if (valid) {
						this.loading = true;
						resetPwd(this.resetForm).then(res => {
							this.$message({
								message: res.msg,
								type: 'success'
							});
							this.$refs.resetForm.resetFields();
							this.loading = false;
						}).catch(err => {
							this.loading = false;
						})
					} else {
						return false;
					}
				});
			}
		}
	}
</script>

<style lang="scss" scoped>
	.user {
		padding: 32px;
		font-size: 16px;
		width: 100%;
		box-sizing: border-box;

		.user-info {
			padding: 24px 16px;
			background-color: #292b3c;
			width: 352px;
			box-sizing: border-box;
			border-radius: 3px;

			.el-input,
			.el-button {
				width: 320px;
			}

			.item {
				display: flex;
				margin-bottom: 16px;

				.label {
					width: 70px;
					text-align: justify;
					margin-right: 16px;
					color: #909bd4;
				}

				.label::after {
					display: inline-block;
					width: 100%;
					content: "";
				}
			}
		}

		.setting-box {

			.setting-box-box {
				padding: 16px;
				width: 320px;
				margin-bottom: 32px;
				background-color: #292b3c;

				.setting-box-item {
					width: 320px;
					display: flex;
					align-items: center;
					margin-bottom: 16px;

					.el-button {
						width: 320px;
					}

					:deep(.el-input__inner) {
						width: 224px;
					}

					.label {
						margin-right: 16px;
						text-align: right;
						min-width: 80px;
						color: #909bd4;
					}
				}

				.setting-box-item:last-child {
					margin-bottom: 0px;
				}

				.setting-tip {
					color: #aaa;
					font-size: 12px;

					.tip-selected {
						color: #fff;
						font-size: 14px;
						line-height: 20px;
					}
				}
			}

			.setting-box-box:last-child {
				margin-bottom: 0px;

			}
		}

		.version {
			position: absolute;
			bottom: 16px;
			left: 0;
			right: 0;
			text-align: center;
		}
	}
</style>