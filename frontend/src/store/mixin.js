import {
	mapState
} from 'vuex'
import store from "@/store";
// 尝试将用户在根目录中的store/index.js的vuex的state变量，全部加载到全局变量中
let $uStoreKey = [];
try {
	$uStoreKey = store.state ? Object.keys(store.state) : [];
} catch (e) {

}

let mixin = {
	created() {
		// 将vuex方法挂在到this中
		this.$setVuex = (name, value) => {
			this.$store.commit('$uStore', {
				name,
				value
			})
		}
	},
	computed: {
		// 将vuex的state中的所有变量，解构到全局混入的mixin中
		...mapState($uStoreKey)
	}
}

export default mixin