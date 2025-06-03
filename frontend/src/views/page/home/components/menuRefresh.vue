<template>
	<div class="menuRefresh">
		&nbsp;
		<div class="refreshLabel" v-show="needShow > 1">{{refreshText}}</div>
		<el-switch v-model="refreshStatus" v-show="needShow > 1" @change="refreshChange"></el-switch>
		<i :class="`${loading ? 'el-icon-loading' : 'el-icon-refresh-right'} icon-btn`" @click="refreshData" v-show="needShow > 0"></i>
	</div>
</template>

<script>
	export default {
		name: 'MenuRefresh',
		props: {
			loading: {
				type: Boolean,
				default: false
			},
			autoRefresh: {
				type: Boolean,
				default: true
			},
			freshInterval: {
				type: Number,
				default: 3119
			},
			needShow: {
				type: Number,
				default: 2 // 0-不显示，1-只显示刷新按钮，2-显示全部
			},
			refreshText: {
				type: String,
				default: '自动刷新'
			}
		},
		data() {
			return {
				refreshStatus: true,
				timer: null
			};
		},
		created() {
			this.refreshStatus = this.autoRefresh;
			if (this.refreshStatus) {
				this.startRefresh();
			} else {
				this.$emit('getData');
			}
		},
		beforeDestroy() {
			this.destroy();
		},
		methods: {
			refreshChange(val) {
				this.refreshStatus = val;
				if (val) {
					this.startRefresh();
				} else {
					this.destroy();
				}
			},
			refreshData() {
				if (!this.loading) {
					this.$emit('getData');
				}
			},
			startRefresh() {
				this.destroy();
				this.$emit('getData');
				this.timer = setInterval(() => {
					this.$emit('getData');
				}, this.freshInterval);
			},
			destroy() {
				if (this.timer) {
					clearInterval(this.timer);
				}
			}
		}
	}
</script>

<style lang="scss" scoped>
	.menuRefresh {
		display: flex;
		align-items: center;

		.refreshLabel {
			font-size: 18px;
			margin-right: 8px;
		}

		.icon-btn {
			font-size: 28px;
			margin-left: 24px;
		}

		.el-icon-refresh-right {
			cursor: pointer;
			color: #1890ff;
		}

		.el-icon-loading {
			cursor: not-allowed;
		}
	}
</style>