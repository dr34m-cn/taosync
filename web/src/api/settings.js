import request from "@/utils/request";

export function getSettings() {
  return request({ url: "/settings", method: "get", headers: { isMask: false } });
}

export function updateSettings(settings) {
  return request({ url: "/settings", method: "put", headers: { isMask: false }, data: { settings } });
}
