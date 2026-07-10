import request from "@/utils/request";

export function getNotifyList() {
  return request({
    url: "/notify",
    headers: { isMask: false },
    method: "get",
  });
}

export function postAddNotify(notify) {
  return request({
    url: "/notify",
    headers: { isMask: false },
    method: "post",
    data: {
      notify,
    },
  });
}

export function putEditNotify(notify) {
  return request({
    url: "/notify",
    headers: { isMask: false },
    method: "put",
    data: {
      notify,
    },
  });
}

export function putEnableNotify(notifyId, enable) {
  return request({
    url: "/notify",
    headers: { isMask: false },
    method: "put",
    data: {
      notifyId,
      enable,
    },
  });
}

export function delNotify(notifyId) {
  return request({
    url: "/notify",
    headers: { isMask: false },
    method: "delete",
    data: {
      notifyId,
    },
  });
}
