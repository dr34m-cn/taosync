import request from "@/utils/request";

export function getSettings() {
  return request({ url: "/settings", method: "get", headers: { isMask: false } });
}

export function getApiKeyStatus(scope = 'general') {
  return request({ url: '/settings/api-key', method: 'get', headers: { isMask: false }, params: { scope } });
}

export function getHttpsStatus() {
  return request({ url: '/settings/https', method: 'get', headers: { isMask: false } });
}

export function applyHttps(data) {
  return request({ url: '/settings/https', method: 'put', headers: { isMask: false }, data });
}

export function clearHttpsCertificate() {
  return request({ url: '/settings/https', method: 'delete', headers: { isMask: false } });
}

export function changeApiKey(action, scope = 'general') {
  return request({ url: '/settings/api-key', method: 'put', headers: { isMask: false }, data: { action, scope } });
}

export function updateSettings(settings) {
  return request({ url: "/settings", method: "put", headers: { isMask: false }, data: { settings } });
}
