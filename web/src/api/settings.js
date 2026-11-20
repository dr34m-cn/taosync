import request from "@/utils/request";

export function getSettings() {
  return request({ url: "/settings", method: "get", headers: { isMask: false } });
}

export function getApiKeyStatus() {
  return request({ url: '/settings/api-key', method: 'get', headers: { isMask: false } });
}

export function changeApiKey(action) {
  return request({ url: '/settings/api-key', method: 'put', headers: { isMask: false }, data: { action } });
}

export function updateSettings(settings) {
  return request({ url: "/settings", method: "put", headers: { isMask: false }, data: { settings } });
}
