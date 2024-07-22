<template>
	<div class="login">
		<div class="loginArea">
			<div class="logo">桃桃的自动同步工具</div>
			<div class="title">密码登录</div>
			<el-form :model="loginForm" :rules="rules" ref="loginForm" label-width="0">
				<el-form-item prop="userName">
					<el-input class="input" placeholder="请输入用户名" prefix-icon="el-icon-user"
						v-model="loginForm.userName"></el-input>
				</el-form-item>
				<el-form-item prop="passwd">
					<el-input placeholder="请输入密码" prefix-icon="el-icon-lock" v-model="loginForm.passwd" show-password
						@keyup.enter.native="login"></el-input>
				</el-form-item>
			</el-form>
			<el-button class="login-button" size="medium" type="primary" :loading="loading" @click="login">登录</el-button>
		</div>
	</div>
</template>

<script>
	import {
		login
	} from "@/api/user";
	export default {
		name: 'Login',
		data() {
			return {
				loginForm: {
					userName: null,
					passwd: null
				},
				loading: false,
				rules: {
					userName: [{
						required: true,
						message: '请输入用户名',
						trigger: 'blur'
					}],
					passwd: [{
						required: true,
						message: '请输入密码',
						trigger: 'blur'
					}]
				}
			};
		},
		created() {},
		methods: {
			login() {
				this.$refs.loginForm.validate((valid) => {
					if (valid) {
						this.loading = true;
						login(this.loginForm).then(res => {
							this.$setVuex('vuex_userInfo', res.data);
							this.$router.replace('/home');
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
	.login {
		display: flex;
		align-items: center;
		position: fixed;
		top: 0;
		bottom: 0;
		left: 0;
		right: 0;
		background: url(~@/assets/img/login-bg.jpg) no-repeat center;
		background-size: cover;

		.loginArea {
			background: rgba(16, 30, 65, 0.95);
			width: 520px;
			box-sizing: border-box;
			padding: 30px 60px;
			border-radius: 4px;
			margin-left: 5%;
			color: #FFF;

			:deep(.el-input) {
				font-size: 20px;

				.el-input__inner {
					background-color: transparent;
					color: #FFF;
					height: 60px;
					font-size: 20px;
					border: 1px solid #FFF;
				}

				.el-input__inner:focus {
					border: 1px solid #409eff;
				}
			}

			:deep(.el-form-item.is-error .el-input__inner) {
				border: 1px solid #F56C6C;
			}

			:deep(.el-input--prefix .el-input__inner) {
				padding-left: 40px;
			}

			:deep(.el-form-item) {
				margin-bottom: 28px;

				.el-form-item__error {
					font-size: 16px;
				}
			}

			:deep(.el-button--primary) {
				font-size: 20px;
				padding: 19px 20px;
			}

			.logo {
				background-image: url('/logo-200-64.png');
				background-position: center 0;
				background-repeat: no-repeat;
				width: 400px;
				padding-top: 80px;
				text-align: center;
				letter-spacing: 6px;
				font-size: 20px;
			}

			.title {
				margin-top: 60px;
				font-size: 24px;
				font-weight: 500;
				color: #ffffff;
				line-height: 28px;
				text-align: center;
				padding-bottom: 13px;
				border-bottom: 1px solid rgba(238, 238, 238, 0.2);
				margin-bottom: 43px;
				position: relative;

				&::after {
					content: "";
					display: block;
					width: 53px;
					height: 6px;
					background: url(~@/assets/img/login-line-rectangle.png);
					margin: 0 auto;
					position: absolute;
					bottom: 0;
					left: 50%;
					transform: translateX(-50%);
				}
			}

			.login-button {
				width: 100%;
				margin: 40px 0;
			}
		}
	}
</style>