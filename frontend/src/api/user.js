import request from '@/utils/request'

// 登录
export function login(data) {
	return request({
		url: '/noAuth/login',
		headers: {
			isMask: false
		},
		method: 'post',
		data
	})
}

// 登出
export function logout() {
	return request({
		url: '/noAuth/login',
		method: 'delete'
	})
}

// 获取当前用户信息
export function user() {
	return request({
		url: '/user',
		method: 'get'
	})
}

// 修改当前用户密码
export function resetPwd(data) {
	return request({
		url: '/user',
		headers: {
			isMask: false
		},
		method: 'put',
		data
	})
}