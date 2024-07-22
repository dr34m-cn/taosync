import Vue from 'vue'
import VueRouter from 'vue-router'
import Layout from '@/views/layout.vue'

const originalPush = VueRouter.prototype.push

VueRouter.prototype.push = function push(location) {
  return originalPush.call(this, location).catch(err => err)
}

Vue.use(VueRouter)

const routes = [{
		path: '/',
		name: '首页',
		meta: {
			disableLeft: true,
			letfIndex: ''
		},
		component: () => import('@/views/index')
	},
	{
		path: '/login',
		name: '登录',
		meta: {
			disableLeft: true,
			letfIndex: ''
		},
		component: () => import('@/views/Login')
	},
	{
		path: '/home',
		component: Layout,
		children: [{
			path: '',
			component: () => import('@/views/page/home/index'),
			name: '作业管理',
			meta: {
				letfIndex: '/home'
			}
		},{
			path: 'task',
			component: () => import('@/views/page/home/task'),
			name: '任务列表',
			meta: {
				letfIndex: '/home'
			}
		},{
			path: 'task/detail',
			component: () => import('@/views/page/home/taskDetail'),
			name: '任务详情',
			meta: {
				letfIndex: '/home'
			}
		}]
	},
	{
		path: '/engine',
		component: Layout,
		children: [{
			path: '',
			component: () => import('@/views/page/engine/index'),
			name: '引擎管理',
			meta: {
				letfIndex: '/engine'
			}
		}]
	},
	{
		path: '/setting',
		component: Layout,
		children: [{
			path: '',
			component: () => import('@/views/page/setting/index'),
			name: '系统设置',
			meta: {
				letfIndex: '/setting'
			}
		}]
	}
]

const router = new VueRouter({
	mode: 'hash',
	routes
})

export default router