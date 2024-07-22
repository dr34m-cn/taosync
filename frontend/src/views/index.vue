<template>
	<div class="index-home-main">
		<div class="content-none-data">
			{{ err }}
		</div>
	</div>
</template>

<script>
	import Cookies from 'js-cookie';
	import {
		user
	} from '@/api/user';
	export default {
		name: 'Index',
		data() {
			return {
				err: '加载中，请稍等...'
			};
		},
		created() {
			this.init();
		},
		methods: {
			init() {
				try {
					if (!Cookies.get("tao_sync")) {
						this.to('/login');
					} else {
						this.getInfo();
					}
				} catch (err) {
					this.err = err;
				}
			},
			getInfo() {
				user().then(res => {
					this.$setVuex('vuex_userInfo', res.data);
					this.to('/home');
				}).catch(err => {
					this.to('/login');
				})
			},
			to(path) {
				this.$router.replace(path);
			}
		}
	}
</script>

<style>
	.index-home-main {
		background-color: #191b2b;
		position: absolute;
		top: 0;
		bottom: 0;
		left: 0;
		right: 0;
	}
</style>