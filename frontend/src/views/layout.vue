<template>
	<div class="layout">
		<div class="lay-left">
			<div class="left-top-logo">
				<div :class="'left-top-logo-in ' + (isCollapse ? 'isCollapse' : '')" @click="toIndex"></div>
			</div>
			<el-menu :default-active="vuex_letfIndex" :router="true" :collapse="isCollapse" class="lay-left-menu">
				<el-menu-item :index="item.index" v-for="item in menuList">
					<i :class="`el-icon-${item.icon}`"></i>
					<span slot="title">{{item.title}}</span>
				</el-menu-item>
			</el-menu>
		</div>
		<div class="lay-right">
			<div class="lay-right-top">
				<div class="top-left">
					<div class="top-icon can-click" @click="isCollapse = !isCollapse">
						<i :class="isCollapse ? 'el-icon-s-unfold' : 'el-icon-s-fold'"></i>
					</div>
				</div>
				<div class="top-right">
					<div class="btn-item can-click" @click="toggleTheme">
						<div class="theme-icon">
							<i :class="vuex_theme === 'dark' ? 'el-icon-sunrise' : 'el-icon-moon'"></i>
						</div>
					</div>
					<div class="btn-item can-click" @click="logout()">
						<div class="top-icon">
							<i class="el-icon-switch-button"></i>
						</div>
						<span>登出</span>
					</div>
				</div>
			</div>
			<div class="lay-right-bottom" v-loading="vuex_loading"
				:style="`width: calc(100vw - ${isCollapse ? 64 : 140}px);`">
				<router-view />
			</div>
		</div>

	</div>
</template>
<script>
	import {
		logout
	} from "@/api/user";
	export default {
		data() {
			return {
				isCollapse: false,
				menuList: [{
						index: '/home',
						title: '作业管理',
						icon: 'data-analysis'
					},{ 
						index: '/engine',
						title: '引擎管理',
						icon: 'receiving'
					},{ 
						index: '/notify',
						title: '通知配置',
						icon: 'bell'
					},
					{
						index: '/setting',
						title: '系统设置',
						icon: 'setting'
					}]
			};
		},
		computed: {
			themeValue: {
				get() {
					return this.vuex_theme === 'dark';
				},
				set(val) {
					// 这个setter实际上不会被直接调用，因为我们使用@change事件处理
				}
			}
		},
		created() {
			this.init();
		},
		beforeDestroy() {},
		watch: {},
		methods: {
		init() {},
		logout() {
			logout().then(res => {
				this.$router.push('/login');
				this.$setVuex('vuex_userInfo', null);
			})
		},
		toIndex() {
			this.$router.push('/');
		},
		changeTheme(value) {
			// 切换主题：true为深色，false为浅色
			const newTheme = value ? 'dark' : 'light';
			this.$setVuex('vuex_theme', newTheme);
			// 更新body类名
			document.body.className = newTheme;
		},
		toggleTheme() {
			// 点击图标切换主题
			const newTheme = this.vuex_theme === 'dark' ? 'light' : 'dark';
			this.$setVuex('vuex_theme', newTheme);
			// 更新body类名
			document.body.className = newTheme;
		}
		}
	}
</script>
<style lang="scss" scoped>
	.layout {
		position: fixed;
		top: 0;
		bottom: 0;
		left: 0;
		right: 0;
		display: flex;
		background-color: var(--bg-primary);
		color: var(--text-primary);

		.lay-left {
			background-color: var(--menu-bg);

			.left-top-logo {
				height: 67px;
				display: flex;
				align-items: center;
				justify-content: center;

				.left-top-logo-in {
					width: 140px;
					height: 44.8px;
					cursor: pointer;
					background-image: url('/logo-200-64.png');
					background-size: 140px 44.8px;
					transition: all .3s ease-in-out;
					background-repeat: no-repeat;
					background-position: 0 0;
				}

				.isCollapse {
					width: 44.8px;
				}
			}

			.lay-left-menu {
				height: 100%;
			}

			.lay-left-menu:not(.el-menu--collapse) {
				width: 140px;
			}
		}

		.lay-right {
			width: 100%;
			height: 100%;

			.lay-right-top {
				height: 50px;
				display: flex;
				justify-content: space-between;
				align-items: center;
				border-bottom: 1px solid var(--border-light);
				font-size: 16px;

				.top-icon {
					height: 50px;
					width: 50px;
					display: flex;
					align-items: center;
					justify-content: center;
					font-size: 26px;
				}

				.can-click {
					cursor: pointer;
				}

				.can-click:hover {
			background-color: var(--bg-tertiary);
		}

				.top-left {
					display: flex;
					align-items: center;
				}

				.top-right {
							display: flex;
							align-items: center;

							.btn-item {
								display: flex;
								align-items: center;
								padding-right: 20px;
								cursor: pointer;
								.el-switch {
									margin-left: 8px;
								}
							}
						}
			}

			.lay-right-bottom {
				height: calc(100% - 51px);
				overflow-y: auto;
				transition: width .3s ease-in-out;
			}
		}
	}
</style>