import request from "@/utils/request";

export function alistGet() {
  return request({
    url: "/alist",
    headers: { isMask: false },
    method: "get",
  });
}

export function alistGetPath(alistId, path) {
  return request({
    url: "/alist",
    headers: { isMask: false },
    method: "get",
    params: {
      alistId,
      path,
    },
  });
}

export function alistPost(data) {
  return request({
    url: "/alist",
    headers: { isMask: false },
    method: "post",
    data,
  });
}

export function alistPut(data) {
  return request({
    url: "/alist",
    headers: { isMask: false },
    method: "put",
    data,
  });
}

export function alistDelete(id) {
  return request({
    url: "/alist",
    headers: { isMask: false },
    method: "delete",
    data: { id },
  });
}

export function jobPost(data) {
  return request({
    url: "/job",
    headers: { isMask: false },
    method: "post",
    data,
  });
}

export function jobGetJob(params) {
  return request({
    url: "/job",
    headers: { isMask: false },
    method: "get",
    params,
  });
}

export function jobPut(data) {
  return request({
    url: "/job",
    headers: { isMask: false },
    method: "put",
    data,
  });
}

export function jobDelete(data) {
  return request({
    url: "/job",
    headers: { isMask: false },
    method: "delete",
    data,
  });
}

export function jobGetTaskCurrent(data) {
  return request({
    url: "/job",
    headers: { isMask: false },
    method: "get",
    params: {
      ...data,
      current: 1,
    },
  });
}

export function jobGetTask(params) {
  return request({
    url: "/job",
    headers: { isMask: false },
    method: "get",
    params,
  });
}

export function jobDeleteTask(taskId) {
  return request({
    url: "/job",
    headers: { isMask: false },
    method: "delete",
    data: { taskId },
  });
}

export function jobGetTaskItem(params) {
  return request({
    url: "/job",
    headers: { isMask: false },
    method: "get",
    params,
  });
}
