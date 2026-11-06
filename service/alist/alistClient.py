"""
@Author：dr34m
@Date  ：2024/7/4 13:57 
"""
import threading
import time

import requests

from common.fileFingerprint import fileFingerprint
from common.intervalGate import IntervalGate
from common.LNG import G


# OpenList/AList 中不缓存目录列表的驱动（driver config NoCache）。对这些存储发送 refresh=true 没有
# 刷新缓存的作用，但 OpenList 本地存储开启“目录大小”后，每次 refresh 都会重新计算整个存储的目录大小，
# 导致列目录耗时数分钟（#218）。
NO_CACHE_DRIVERS = {'local'}
STORAGE_CACHE_SECONDS = 300


def checkExs(path, rts, spec):
    """
    检查并排除排除项
    :param path: 所在路径
    :param rts: 内容列表，例如
        {
            "test1-1/": {},  # key以/结尾表示目录
            "test1.txt": 4  # 不以/结尾，表示文件，存文件大小
        }
    :param spec: 排除规则
    :return: 排除后的内容列表
    """
    rtsNew = rts.copy()
    base_path = str(path or "").strip("/")
    for rtsItem in rts.keys():
        candidate = "/".join(part for part in (base_path, rtsItem) if part)
        if spec.match_file(candidate):
            del rtsNew[rtsItem]
    return rtsNew


class AlistClient:
    def __init__(self, url, token, alistId=None):
        """
        初始化
        :param url: 请求地址，例如'http://localhost:5244'，注意结尾不要/
        :param alistId: 存在数据库中的id
        :param token: 登录鉴权信息
        """
        self.url = url
        self.user = None
        self.alistId = alistId
        self.token = token
        # 按根目录排队的扫描间隔控制
        self.waitGate = IntervalGate()
        # 挂载路径 -> 驱动名，用于判断是否需要 refresh
        self.storageDrivers = None
        self.storageDriversTime = 0.0
        self.storageLock = threading.Lock()
        self.getUser()

    def req(self, method, url, data=None, params=None):
        """
        通用请求
        :param method: get/post
        :param url: 请求地址，/api/xxx
        :param data: 需要放在请求体中用json传的数据
        :param params: 在url中的请求参数
        :return: 200返回res['data']，401自动登录后重试，失败抛出异常
        """
        res = {
            'code': 500,
            'message': None,
            'data': None
        }
        headers = None
        if self.token is not None:
            headers = {
                'Authorization': self.token
            }
        try:
            r = requests.request(method, self.url + url, json=data, params=params, headers=headers, timeout=(60, 300))
            if r.status_code == 200:
                res = r.json()
            else:
                res['code'] = r.status_code
                res['message'] = G('code_not_200')
        except Exception as e:
            if 'Invalid URL' in str(e):
                raise Exception(G('address_incorrect'))
            elif 'Max retries' in str(e):
                raise Exception(G('alist_connect_fail'))
            raise Exception(e)
        if res['code'] != 200:
            if res['code'] == 401:
                raise Exception(G('alist_un_auth'))
            raise Exception(G('alist_fail_code_reason').format(res['code'], res['message']))
        return res['data']

    def post(self, url, data=None, params=None):
        """
        发送post请求
        :param url: 请求地址，/api/xxx
        :param data: 需要放在请求体中用json传的数据
        :param params: 放在url中的请求参数
        :return: 200返回res['data']，401自动登录后重试，失败抛出异常
        """
        return self.req('post', url, data, params)

    def get(self, url, params=None):
        """
        发送get请求
        :param url: 请求地址，/api/xxx
        :param params: 放在url中的请求参数
        :return: 200返回res['data']，401自动登录后重试，失败抛出异常
        """
        return self.req('get', url, params=params)

    def getUser(self):
        """
        获取当前用户
        :return:
        """
        self.user = self.get('/api/me')['username']

    def updateAlistId(self, alistId):
        """
        更新alistId
        :param alistId:
        :return:
        """
        self.alistId = alistId

    def checkWait(self, path, scanInterval=0):
        """
        检查是否等待：同一顶层目录下的请求按 scanInterval 秒均匀排队（多线程共享）
        :param path: 路径
        :param scanInterval: 间隔
        :return:
        """
        if not scanInterval:
            return
        parts = str(path).split('/', maxsplit=2)
        pathFirst = parts[1] if len(parts) > 1 else parts[0]
        self.waitGate.wait(pathFirst, scanInterval)

    def _storageDriverMap(self):
        now = time.monotonic()
        with self.storageLock:
            if self.storageDrivers is not None and now - self.storageDriversTime < STORAGE_CACHE_SECONDS:
                return self.storageDrivers
        drivers = {}
        try:
            data = self.get('/api/admin/storage/list') or {}
            for item in data.get('content') or []:
                mount = '/' + str(item.get('mount_path') or '').strip('/')
                drivers[mount] = str(item.get('driver') or '').strip().lower()
        except Exception:
            # 非管理员令牌或旧版本接口不可用：保持原有行为（总是 refresh）
            drivers = {}
        with self.storageLock:
            self.storageDrivers = drivers
            self.storageDriversTime = now
        return drivers

    def shouldRefresh(self, path, useCache=0):
        """未开启缓存时请求 refresh；但对不缓存的存储（如本地存储）跳过，避免触发昂贵的重新计算。"""
        if useCache == 1:
            return False
        normalized = '/' + str(path).strip('/')
        best = None
        for mount, driver in self._storageDriverMap().items():
            if normalized == mount or normalized.startswith(mount.rstrip('/') + '/'):
                if best is None or len(mount) > len(best[0]):
                    best = (mount, driver)
        return not (best is not None and best[1] in NO_CACHE_DRIVERS)

    def fileListApi(self, path, useCache=0, scanInterval=0, spec=None, rootPath=None):
        """
        目录列表
        :param path: 目录，以/开头并以/结尾
        :param useCache: 是否使用缓存，0-不使用，1-使用
        :param scanInterval: 目录扫描间隔，单位秒
        :param spec: 排除项规则
        :return: {
            "test1-1/": {},  # key以/结尾表示目录
            "test1.txt": 4  # 不以/结尾，表示文件，存文件大小
        }
        :param rootPath: 同步根目录
        """
        details = self.fileListDetailApi(
            path, useCache, scanInterval, spec, rootPath
        )
        return {
            name: {} if detail['isDir'] else detail['size']
            for name, detail in details.items()
        }

    def fileListDetailApi(self, path, useCache=0, scanInterval=0, spec=None, rootPath=None):
        """Return AList entries with stable metadata while keeping fileListApi compatible."""
        self.checkWait(path, scanInterval)
        res = self.post('/api/fs/list', data={
            'path': path,
            'refresh': self.shouldRefresh(path, useCache)
        })['content']
        if res is not None:
            rts = {
                f"{item['name']}/" if item['is_dir'] else item['name']: {
                    'isDir': 1 if item['is_dir'] else 0,
                    'size': None if item['is_dir'] else item['size'],
                    'fingerprint': fileFingerprint(
                        'alist',
                        item.get('hash_info') or item.get('hash'),
                        item.get('modified') or item.get('updated_at'),
                    ),
                } for item in res
            }
        else:
            rts = {}
        if spec and rts:
            if rootPath is None:
                rootPath = path
            rts = checkExs(path[len(rootPath):], rts, spec)
        return rts

    def filePathList(self, path):
        """
        通过路径获取其下路径列表
        :param path:
        :return:
        """
        res = self.post('/api/fs/list', data={
            'path': path,
            'refresh': self.shouldRefresh(path)
        })['content']
        if res is not None:
            return [{'path': item['name']} for item in res if item['is_dir']]
        else:
            return []

    def allFileList(self, path, useCache=0, scanInterval=0, spec=None, rootPath=None):
        """
        递归获取文件列表，暂时弃用
        :param path: 根路径
        :param useCache: 是否使用缓存，0-不使用，1-使用
        :param scanInterval: 目录扫描间隔，单位秒
        :param spec: 排除项规则
        :param rootPath: 同步根目录
        :return: {
            "test1-1/": {
                "test1-3/": {
                    "test1.txt": 4
                },
                "test1.txt": 4
            },
            "test1.txt": 4
        }
        """
        if rootPath is None:
            rootPath = path
        fList = self.fileListApi(path, useCache, scanInterval, spec, rootPath)
        for key in fList.keys():
            if key.endswith('/'):
                fList[key] = self.allFileList(f"{path}/{key[:-1]}", useCache, scanInterval, spec, rootPath)
        return fList

    def mkdir(self, path, scanInterval=0):
        """
        创建目录
        :param path: 路径
        :param scanInterval:
        """
        self.checkWait(path, scanInterval)
        return self.post('/api/fs/mkdir', data={
            'path': path
        })

    def deleteFile(self, path, names, scanInterval=0):
        """
        删除文件或目录
        :param path: 路径
        :param names: 文件/目录名，列表
        :param scanInterval:
        """
        self.checkWait(path, scanInterval)
        self.post('/api/fs/remove', data={
            'names': names,
            'dir': path
        })

    def copyFile(self, srcDir, dstDir, name):
        """
        复制文件
        :param srcDir: 源目录
        :param dstDir: 目标目录
        :param name: 文件名
        :return: 任务id
        """
        tasks = self.post('/api/fs/copy', data={
            'src_dir': srcDir,
            'dst_dir': dstDir,
            'overwrite': True,
            'names': [
                name
            ]
        })['tasks']
        if tasks:
            return tasks[0]['id']
        else:
            return None

    def moveFile(self, srcDir, dstDir, name):
        """
        移动文件
        :param srcDir: 源目录
        :param dstDir: 目标目录
        :param name: 文件名
        :return: 任务id
        """
        tasks = self.post('/api/fs/move', data={
            'src_dir': srcDir,
            'dst_dir': dstDir,
            'overwrite': True,
            'names': [
                name
            ]
        })['tasks']
        if tasks:
            return tasks[0]['id']
        else:
            return None

    def taskInfo(self, taskId):
        """
        任务详情
        :param taskId: 任务id
        :return: {
            "id": "26GQSD1mZHDlDq1V1Lf7G",
            "name": "copy [/test1](/test1/test1.txt) to [/test2](/)",
            "state": 2, # 0-等待中，1-进行中，2-成功
            "status": "getting src object",
            "progress": 0, # 进度
            "error": ""
        }
        """
        return self.post('/api/admin/task/copy/info', params={
            'tid': taskId
        })

    def copyTaskDone(self):
        """
        已完成的复制任务
        :return: [{
            "id": "26GQSD1mZHDlDq1V1Lf7G",
            "name": "copy [/test1](/test1/test1.txt) to [/test2](/)",
            "state": 2, # 0-等待中，1-进行中，2-成功
            "status": "getting src object",
            "progress": 0, # 进度
            "error": ""
        }]
        """
        return self.get('/api/admin/task/copy/done')

    def copyTaskUnDone(self):
        """
        未完成的复制任务
        :return: [{
            "id": "26GQSD1mZHDlDq1V1Lf7G",
            "name": "copy [/test1](/test1/test1.txt) to [/test2](/)",
            "state": 1, # 0-等待中，1-进行中，2-成功
            "status": "getting src object",
            "progress": 0, # 进度
            "error": ""
        }]
        """
        return self.get('/api/admin/task/copy/undone')

    def copyTaskRetry(self, taskId):
        """
        重试复制任务
        :param taskId: 任务id
        """
        self.post('/api/admin/task/copy/retry', params={
            'tid': taskId
        })

    def copyTaskClearSucceeded(self):
        """
        清除已成功的复制任务
        """
        self.post('/api/admin/task/copy/clear_succeeded')

    def copyTaskDelete(self, taskId):
        """
        删除复制任务
        :param taskId: 任务id
        """
        self.post('/api/admin/task/copy/delete', params={
            'tid': taskId
        })

    def copyTaskCancel(self, taskId):
        """
        取消复制任务
        :param taskId: 任务id
        """
        self.post('/api/admin/task/copy/cancel', params={
            'tid': taskId
        })
