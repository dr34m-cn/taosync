import request from '@/utils/request'

// 通知列表
export function getNotifyList() {
	return request({
		url: '/notify',
		headers: {
			isMask: false
		},
		method: 'get'
	})
}

// 新增/测试通知
export function postAddNotify(notify) {
	return request({
		url: '/notify',
		headers: {
			isMask: false
		},
		method: 'post',
		data: {
			notify
		}
	})
}

// 修改通知
export function putEditNotify(notify) {
	return request({
		url: '/notify',
		headers: {
			isMask: false
		},
		method: 'put',
		data: {
			notify
		}
	})
}

// 启用/禁用通知
export function putEnableNotify(notifyId, enable) {
	return request({
		url: '/notify',
		headers: {
			isMask: false
		},
		method: 'put',
		data: {
			notifyId,
			enable
		}
	})
}

// 删除通知
export function delNotify(notifyId) {
	return request({
		url: '/notify',
		headers: {
			isMask: false
		},
		method: 'delete',
		data: {
			notifyId
		}
	})
}