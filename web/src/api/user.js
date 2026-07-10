import request from "@/utils/request";

// 登录
export function login(data) {
  return request({
    url: "/noAuth/login",
    headers: {
      isMask: false,
    },
    method: "post",
    data,
  });
}

// 登出
export function logout() {
  return request({
    url: "/noAuth/login",
    method: "delete",
  });
}

// 重置密码
export function resetPwd(data) {
  return request({
    url: "/noAuth/login",
    headers: {
      isMask: false,
    },
    method: "put",
    data,
  });
}

// 获取当前用户信息
export function getUser() {
  return request({
    url: "/user",
    method: "get",
  });
}

export const user = getUser;

// 修改当前用户密码
export function putUser(data) {
  return request({
    url: "/user",
    headers: {
      isMask: false,
    },
    method: "put",
    data,
  });
}

export const editPwd = putUser;
