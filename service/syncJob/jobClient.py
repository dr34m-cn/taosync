"""
@Author：dr34m
@Date  ：2024/7/11 12:14 
"""
import logging
import threading
import time

from apscheduler.schedulers.blocking import BlockingScheduler

from common.config import CONFIG
from mapper import jobMapper
from service.alist import alistSync, alistService

timeOut = int(CONFIG['server']['timeout'])


class JobTask:
    def __init__(self, taskId, job):
        self.taskId = taskId
        self.job = job
        self.client = alistService.getClientById(self.job['alistId'])
        self.taskItemList = []
        self.sync()

    def copyHook(self, srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None):
        """
        复制文件回调
        :param srcPath: 来源目录
        :param dstPath: 目标目录
        :param name: 文件名
        :param size: 文件大小
        :param alistTaskId: alist任务id
        :param status: 0-等待中，1-运行中，2-成功，3-取消中，4-已取消，5-出错（将重试），6-失败中，
                        7-已失败，8-等待重试中，9-等待重试回调执行中
        :param errMsg: 错误信息
        """
        self.taskItemList.append({
            'taskId': self.taskId,
            'srcPath': srcPath,
            'dstPath': dstPath,
            'fileName': name,
            'fileSize': size,
            'type': 0,
            'alistTaskId': alistTaskId,
            'status': status,
            'errMsg': errMsg
        })

    def delHook(self, dstPath, name, size, status=2, errMsg=None):
        """
        删除文件回调
        :param dstPath: 目标目录
        :param name: 文件名
        :param size: 文件大小
        :param status: 2-成功、7-失败
        :param errMsg: 错误信息
        """
        self.taskItemList.append({
            'taskId': self.taskId,
            'srcPath': None,
            'dstPath': dstPath,
            'fileName': name,
            'fileSize': size,
            'type': 1,
            'alistTaskId': None,
            'status': status,
            'errMsg': errMsg
        })

    def sync(self):
        """
        执行同步
        """
        alistSync.sync(self.job['srcPath'], self.job['dstPath'], self.job['alistId'],
                       self.job['speed'], self.job['method'], self.copyHook, self.delHook)
        jobMapper.addJobTaskItemMany(self.taskItemList)
        self.updateItemStatus()

    def updateItemStatus(self):
        """
        更新任务子项状态
        """
        tmStart = time.time()
        undoneTaskItem = jobMapper.getUndoneJobTaskItemList(self.taskId)
        while undoneTaskItem:
            if time.time() - tmStart > timeOut * 3600:
                jobMapper.updateJobTaskStatus(self.taskId, 5)
                return
            needUpdate = []
            for item in undoneTaskItem[:]:
                try:
                    taskInfo = self.client.taskInfo(item['alistTaskId'])
                except Exception as e:
                    eMsg = str(e)
                    if 'AList返回404错误' in eMsg:
                        eMsg = ("任务未找到。可能是您手动到AList中删除了复制任务；"
                                "或者Alist因手动/异常奔溃被重启，导致任务记录丢失/task not found."
                                "You may have manually deleted the replication task in AList;"
                                "or Alist was restarted manually or abnormally, resulting in the loss of task records.")
                    taskInfo = {
                        'state': 7,
                        'progress': None,
                        'error': eMsg
                    }
                if taskInfo['state'] == item['status'] and taskInfo['progress'] == item['progress']:
                    continue
                needUpdate.append({
                    'id': item['id'],
                    'status': taskInfo['state'],
                    'progress': taskInfo['progress'],
                    'errMsg': taskInfo['error'] if taskInfo['error'] is not None and taskInfo['error'] != '' else None
                })
                # 删除成功的记录
                if taskInfo['state'] == 2:
                    self.client.copyTaskDelete(item['alistTaskId'])
                if taskInfo['state'] in [2, 4, 7]:
                    undoneTaskItem.remove(item)
            if needUpdate:
                jobMapper.updateJobTaskItemStatusByIdMany(needUpdate)
            if undoneTaskItem:
                time.sleep(10)
        self.updateTaskStatus()

    def updateTaskStatus(self):
        """
        更新任务状态
        """
        unSuccessTaskItem = jobMapper.getUnSuccessJobTaskItemList(self.taskId)
        status = 2 if not unSuccessTaskItem else 3
        jobMapper.updateJobTaskStatus(self.taskId, status)


class JobClient:
    def __init__(self, job):
        """
        初始化job
        :param job: {id(新增时不需要), enable, srcPath, dstPath, alistId, speed, method, interval}
        """
        job['id'] = job['id'] if 'id' in job else jobMapper.addJob(job)
        if 'enable' not in job:
            job['enable'] = 1
        if 'speed' not in job:
            job['speed'] = 0
        if 'method' not in job:
            job['method'] = 0
        self.jobId = job['id']
        self.job = job
        self.interval = job['interval']
        self.scheduled = None
        if self.job['enable'] == 1:
            self.createJob()

    def doJob(self):
        """
        执行作业
        :return:
        """
        try:
            taskId = jobMapper.addJobTask({
                'jobId': self.jobId,
                'runTime': int(time.time())
            })
            JobTask(taskId, self.job)
        except Exception as e:
            logger = logging.getLogger()
            logger.error(f"执行任务失败，原因为：{str(e)}")
            logger.exception(e)

    def doByTime(self):
        self.doJob()
        self.scheduled = BlockingScheduler()
        self.scheduled.add_job(self.doJob, 'interval', minutes=self.interval)
        self.scheduled.start()

    def createJob(self):
        """
        创建作业定时任务
        :return:
        """
        if self.job['enable'] == 0:
            jobMapper.updateJobEnable(self.jobId, 1)
            self.job['enable'] = 1
        doJobThread = threading.Thread(target=self.doByTime)
        doJobThread.start()
        time.sleep(0.5)

    def stopJob(self, remove=False):
        """
        停止作业（适用于修改enable）
        :param remove: 是否删除作业，否一般用于禁用作业
        :return:
        """
        if self.scheduled is not None:
            try:
                self.scheduled.shutdown(wait=False)
            except Exception as e:
                logger = logging.getLogger()
                logger.warning(f"停止定时任务失败，原因为：{str(e)}")
                logger.exception(e)
            self.scheduled = None
        if remove:
            jobMapper.deleteJob(self.jobId)
        else:
            self.job['enable'] = 0
            jobMapper.updateJobEnable(self.jobId, 0)
            jobMapper.updateJobTaskStatusByStatusAndJobId(self.jobId)
