import Vue from 'vue'
import Vuex from 'vuex'
Vue.use(Vuex)

let lifeData = {};
try {
	lifeData = JSON.parse(localStorage.getItem('lifeData') || "{}");
} catch (err) {
	localStorage.setItem('lifeData', "{}");
	lifeData = {};
}

// 需要永久存储，且下次APP启动需要取出的，在state中的变量名
let saveStateKeys = ['vuex_userInfo'];

// 保存变量到本地存储中
const saveLifeData = function(key, value) {
	// 判断变量名是否在需要存储的数组中
	if (saveStateKeys.indexOf(key) != -1) {
		// 获取本地存储的lifeData对象，将变量添加到对象中
		let tmp = JSON.parse(localStorage.getItem('lifeData'));
		// 第一次打开APP，不存在lifeData变量，故放一个{}空对象
		tmp = tmp ? tmp : {};
		tmp[key] = value;
		// 执行这一步后，所有需要存储的变量，都挂载在本地的lifeData对象中
		localStorage.setItem('lifeData', JSON.stringify(tmp));
	}
}
const store = new Vuex.Store({
	state: {
		vuex_userInfo: lifeData.vuex_userInfo ? lifeData.vuex_userInfo : null, // 用户信息
		vuex_loading: false, // 加载蒙版显示与否
		vuex_onRequest: false, // 是否请求中
		vuex_letfIndex: null,
		vuex_cookieName: 'tao_sync'
	},
	mutations: {
		$uStore(state, payload) {
			// 判断是否多层级调用，state中为对象存在的情况，诸如user.info.score = 1
			let nameArr = payload.name.split('.');
			let saveKey = '';
			let len = nameArr.length;
			if (nameArr.length >= 2) {
				let obj = state[nameArr[0]];
				for (let i = 1; i < len - 1; i++) {
					obj = obj[nameArr[i]];
				}
				obj[nameArr[len - 1]] = payload.value;
				saveKey = nameArr[0];
			} else {
				state[payload.name] = payload.value;
				saveKey = payload.name;
			}
			// 保存变量到本地，见顶部函数定义
			saveLifeData(saveKey, state[saveKey])
		}
	}
})

export default store