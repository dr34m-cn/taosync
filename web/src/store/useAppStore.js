import { defineStore } from "pinia";

export const useAppStore = defineStore("app", {
  state: () => ({
    user: null,
    login: null,
    leftIndex: "/home",
    loading: false,
    onRequest: false,
    cookieName: "tao_sync",
  }),

  actions: {
    set(key, value) {
      this[key] = value;
    },
    setLegacy(key, value) {
      const map = {
        vuex_userInfo: "user",
        vuex_loading: "loading",
        vuex_onRequest: "onRequest",
        vuex_letfIndex: "leftIndex",
        vuex_cookieName: "cookieName",
      };
      this[map[key] || key] = value;
    },
  },

  // 持久化配置
  persist: {
    storage: localStorage,
    pick: ["user", "login"],
  },
});
