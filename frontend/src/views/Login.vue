<template>
	<div class="login" :style="{ backgroundImage: `url(${vuex_theme === 'dark' ? require('@/assets/img/login-bg.jpg') : require('@/assets/img/login-bg-light.svg')})` }">
		<div class="theme-toggle" @click="toggleTheme">
			<i :class="vuex_theme === 'dark' ? 'el-icon-sunrise' : 'el-icon-moon'"></i>
		</div>
		<div class="loginArea" :style="{ background: vuex_theme === 'dark' ? 'rgba(16, 30, 65, 0.95)' : 'rgba(255, 255, 255, 0.95)' }">
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
			<div class="foget" @click="fogetPwd">忘记密码？</div>
			<el-button class="login-button" size="medium" type="primary" :loading="loading"
				@click="login">登录</el-button>
		</div>
		<el-dialog :close-on-click-modal="false" :visible.sync="showPwd" :append-to-body="true" title="重置密码"
			width="560px" :before-close="closePwd">
			<div>
				<el-form :model="pwdForm" :rules="pwdRules" ref="resetForm" label-width="80px">
					<el-form-item prop="userName" label="用户名">
						<el-input class="input" placeholder="请输入用户名" v-model="pwdForm.userName"></el-input>
					</el-form-item><el-form-item prop="key" label="加密秘钥">
						<el-input class="input" placeholder="在[程序同级]或[docker挂载]目录[data/secret.key]文件中复制全部"
							v-model="pwdForm.key"></el-input>
					</el-form-item>
					<el-form-item prop="passwd" label="新密码">
						<el-input placeholder="请输入新密码" v-model="pwdForm.passwd" show-password></el-input>
					</el-form-item>
					<el-form-item prop="passwd2" label="确认密码">
						<el-input placeholder="请确认新密码" v-model="pwdForm.passwd2" show-password></el-input>
					</el-form-item>
				</el-form>
			</div>
			<span slot="footer" class="dialog-footer">
				<el-button @click="closePwd">取 消</el-button>
				<el-button type="primary" @click="fogetSubmit" :loading="loading">确 定</el-button>
			</span>
		</el-dialog>
	</div>
</template>

<script>
	import Cookies from 'js-cookie';
	import {
		login,
		resetPwd
	} from "@/api/user";
	export default {
		name: 'Login',
		data() {
			var validatePass2 = (rule, value, callback) => {
				if (value == '' || value == null) {
					callback(new Error('请再次输入新密码'));
				} else if (value !== this.pwdForm.passwd) {
					callback(new Error('两次输入密码不一致!'));
				} else {
					callback();
				}
			};
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
				},
				pwdRules: {
					userName: [{
						required: true,
						message: '请输入用户名',
						trigger: 'blur'
					}],
					key: [{
						required: true,
						message: '请输入key',
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
				},
				showPwd: false,
				pwdForm: {
					userName: null,
					key: null,
					passwd: null,
					passwd2: null
				}
			};
		},
		computed: {
			vuex_theme() {
				return this.$store.state.vuex_theme;
			}
		},
		created() {
			// 应用主题到body
			document.body.className = this.vuex_theme;
		},
		methods: {
			login() {
				this.$refs.loginForm.validate((valid) => {
					if (valid) {
						Cookies.remove(this.vuex_cookieName);
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
			},
			toggleTheme() {
				// 切换主题
				const newTheme = this.vuex_theme === 'dark' ? 'light' : 'dark';
				this.$setVuex('vuex_theme', newTheme);
				// 更新body类名
				document.body.className = newTheme;
			},
			fogetPwd() {
				this.showPwd = true;
			},
			closePwd() {
				this.showPwd = false;
				this.pwdForm = {
					userName: null,
					key: null,
					passwd: null,
					passwd2: null
				}
			},
			fogetSubmit() {
				this.$refs.resetForm.validate((valid) => {
					if (valid) {
						this.loading = true;
						resetPwd(this.pwdForm).then(res => {
							this.closePwd();
							this.$message({
								message: '密码重置成功，请使用新密码登录',
								type: 'success'
							});
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
		background-size: cover;
		background-position: center;
		background-repeat: no-repeat;
		
		.theme-toggle {
			position: absolute;
			top: 20px;
			right: 20px;
			font-size: 28px;
			cursor: pointer;
			color: #409eff;
			transition: all 0.3s ease;
			z-index: 1000;
			
			&:hover {
				transform: scale(1.2);
			}
		}

		.loginArea {
			background: rgba(16, 30, 65, 0.95);
			width: 520px;
			box-sizing: border-box;
			padding: 30px 60px;
			border-radius: 4px;
			margin-left: 5%;
			color: var(--text-primary);
			position: relative;

			:deep(.el-input) {
				font-size: 20px;

				.el-input__inner {
					background-color: transparent;
					color: var(--text-primary);
					height: 60px;
					font-size: 20px;
					border: 1px solid var(--border-light);
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
					color: #F56C6C;
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
				color: var(--text-primary);
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
				margin: 20px 0 20px 0;
			}

			.foget {
				text-align: right;
				cursor: pointer;
				color: #409eff;
			}

			.theme-toggle {
				position: absolute;
				top: 20px;
				right: 20px;
				cursor: pointer;
				padding: 10px;
				
				i {
					font-size: 28px;
				}
			}
		}
	}
</style>