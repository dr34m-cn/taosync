<template>
	<div id="app" class="app-all-main">
		<div>
			<router-view />
		</div>
	</div>
</template>
<script>
	export default {
		name: "App",
		data() {
			return {
				timer: null
			};
		},
		watch: {
			$route(to, from) {
				this.$setVuex('vuex_letfIndex', to.meta ? (to.meta.letfIndex || null) : null);
			}
		},
		created() {},
		beforeDestroy() {},
		methods: {}
	};
</script>
<style lang="scss">
	body {
		margin: 0;
		padding: 0;
		font-size: 16px;
	}


	::-webkit-scrollbar {
		width: 5px;
		height: 5px;
	}

	::-webkit-scrollbar-thumb {
		background-color: #3c3f4d;
	}

	::-webkit-scrollbar-track {
		-webkit-box-shadow: transparent;
		background: transparent;
	}

	.app-all-main {}
</style>