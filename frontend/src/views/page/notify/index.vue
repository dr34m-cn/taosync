<template>
	<div class="notify" v-loading="getLoading">
	</div>
</template>

<script>
	export default {
		name: 'Notify',
		components: {},
		data() {
			return {};
		},
		created() {},
		beforeDestroy() {},
		methods: {}
	}
</script>

<style lang="scss" scoped>
	.notify {
		box-sizing: border-box;
		padding: 8px;
		width: 100%;
		height: 100%;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(340px, 2fr));
	}
</style>