import request from '@/utils/request'

// alist列表
export function alistGet() {
	return request({
		url: '/alist',
		headers: {
			isMask: false
		},
		method: 'get'
	})
}

// alist子目录
export function alistGetPath(alistId, path) {
	return request({
		url: '/alist',
		headers: {
			isMask: false
		},
		method: 'get',
		params: {
			alistId,
			path
		}
	})
}

export function localGetPath(localRootDir, path) {
	return request({
		url: '/local',
		headers: {
			isMask: false
		},
		method: 'get',
		params: {
			localRootDir,
			path
		}
	})
}

// alist新增
export function alistPost(data) {
	return request({
		url: '/alist',
		headers: {
			isMask: false
		},
		method: 'post',
		data
	})
}

// alist修改
export function alistPut(data) {
	return request({
		url: '/alist',
		headers: {
			isMask: false
		},
		method: 'put',
		data
	})
}

// 删除alist
export function alistDelete(id) {
	return request({
		url: '/alist',
		headers: {
			isMask: false
		},
		method: 'delete',
		data: {
			id
		}
	})
}

// 创建作业
export function jobPost(data) {
	return request({
		url: '/job',
		headers: {
			isMask: false
		},
		method: 'post',
		data
	})
}

// 作业列表
export function jobGetJob(params) {
	return request({
		url: '/job',
		headers: {
			isMask: false
		},
		method: 'get',
		params
	})
}

// 禁用/启用作业/手动执行
export function jobPut(data) {
	return request({
		url: '/job',
		headers: {
			isMask: false
		},
		method: 'put',
		data
	})
}

// 删除作业
export function jobDelete(data) {
	return request({
		url: '/job',
		headers: {
			isMask: false
		},
		method: 'delete',
		data
	})
}

// 任务列表
export function jobGetTask(params) {
	return request({
		url: '/job',
		headers: {
			isMask: false
		},
		method: 'get',
		params
	})
}

// 删除任务
export function jobDeleteTask(taskId) {
	return request({
		url: '/job',
		headers: {
			isMask: false
		},
		method: 'delete',
		data: {
			taskId
		}
	})
}

// 任务详情列表
export function jobGetTaskItem(params) {
	return request({
		url: '/job',
		headers: {
			isMask: false
		},
		method: 'get',
		params
	})
}