import Vue from 'vue';
import ElementUI from 'element-ui';
import 'element-ui/lib/theme-chalk/index.css';
import mixin from "@/store/mixin.js";
import "@/assets/style/style.scss";

import store from '@/store';
Vue.mixin(mixin);

import filters from '@/utils/filters';
Object.keys(filters).forEach(k => Vue.filter(k, filters[k]));

import App from './App.vue';
import router from './router';

window.mseResource = new Map();

Vue.config.productionTip = false

Vue.use(ElementUI)

new Vue({
	store,
	router,
	render: h => h(App),
	created() {
		// 初始化主题
		const theme = this.$store.state.vuex_theme;
		document.body.className = theme;
	}
}).$mount('#app')
