import i18n from "./i18n";
import axios from "axios";
import { ElMessage, ElMessageBox, ElNotification } from "element-plus";
import router from "@/router";
import { useAppStore } from "@/store/useAppStore";
import errorCode from "@/utils/errorCode";
import Cookies from "js-cookie";
const { t } = i18n.global;
let timeout = 90000;
export const isRelogin = {
  show: false,
};

axios.defaults.headers["Content-Type"] = "application/json;charset=utf-8";
const service = axios.create({
  baseURL: "/svr",
  timeout,
});
// request拦截器
service.interceptors.request.use(
  (config) => {
    const appStore = useAppStore();
    const isMask = (config.headers || {}).isMask === false;
    config.headers["Accept-Language"] = localStorage.getItem("lang") || "zh-CN";
    appStore.set("onRequest", true);
    if (!isMask) {
      setTimeout(() => {
        if (appStore.onRequest) {
          appStore.set("loading", true);
        }
      }, 300);
    }
    return config;
  },
  (error) => {
    console.log(error);
    Promise.reject(error);
  }
);

// 响应拦截器
service.interceptors.response.use(
  async (res) => {
    const appStore = useAppStore();
    appStore.set("onRequest", false);
    appStore.set("loading", false);
    // 导出等二进制响应错误处理
    if (res.data.type == "application/json") {
      const blob = new Blob([res.data], { type: "application/json" });
      const rdt = await blob.text();
      res.data = JSON.parse(rdt);
    }
    const code = res.data?.code || 200;
    let msg = res.data?.msg || t(errorCode[code] || errorCode.default);
    if (msg.includes("timed out")) {
      msg = t("network.timeout");
    }
    // 二进制数据则直接返回
    const contentType = res.headers["content-type"] || "application/json; charset=UTF-8";
    if (!contentType.includes("application/json") && !contentType.includes("text/html")) {
      return res;
    }
    if (code === 401) {
      appStore.set("user", null);
      const currentRoute = router.currentRoute.value;
      const isAuthenticatedRoute = Boolean(currentRoute.meta?.leftIndex);
      if (!isAuthenticatedRoute) {
        if (currentRoute.path !== "/login") {
          Cookies.remove(appStore.cookieName);
          router.replace("/login");
        }
        return Promise.reject(t("network.loginExpired"));
      }
      if (!isRelogin.show) {
        isRelogin.show = true;
        ElMessageBox.confirm(t("network.loginExpiredMessage"), t("common.tips"), {
          confirmButtonText: t("network.relogin"),
          cancelButtonText: t("common.cancel"),
          type: "warning",
          closeOnClickModal: false,
        })
          .then(() => {
            Cookies.remove(appStore.cookieName);
            router.replace("/login");
          })
          .catch(() => {})
          .finally(() => {
            isRelogin.show = false;
          });
      }
      return Promise.reject(t("network.loginExpired"));
    } else if (code === 500) {
      ElMessage({
        message: msg,
        type: "error",
        duration: 5 * 1000,
      });
      return Promise.reject(new Error(msg));
    } else if (code !== 200) {
      ElNotification.error({
        title: msg,
      });
      return Promise.reject(msg);
    } else {
      return res.data;
    }
  },
  (error) => {
    const appStore = useAppStore();
    appStore.set("onRequest", false);
    appStore.set("loading", false);
    console.log("err" + error);
    let { message } = error;
    if (message == "Network Error") {
      message = t("network.networkErr");
    } else if (message.includes("timeout")) {
      message = t("network.timeout");
    } else if (message.includes("Request failed with status code")) {
      message = t("network.codeErr", { code: message.substr(message.length - 3) });
    }
    ElNotification({
      message: message,
      type: "error",
      duration: 5 * 1000,
    });
    return Promise.reject(error);
  }
);

export default service;
