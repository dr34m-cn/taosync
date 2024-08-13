"""
@Author：dr34m
@Date  ：2024/7/11 12:14 
"""
import logging
import threading
import time

from apscheduler.schedulers.background import BackgroundScheduler

from common.config import getConfig
from mapper import jobMapper
from service.alist import alistSync, alistService

CONFIG = getConfig()
timeOut = CONFIG['server']['timeout']


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
                       self.job['speed'], self.job['method'], self.copyHook, self.delHook, self.job)
        jobMapper.addJobTaskItemMany(self.taskItemList)
        self.updateItemStatus()

    def updateItemStatus(self):
        """
        更新任务子项状态
        """
        tmStart = time.time()
        undoneTaskItem = jobMapper.getUndoneJobTaskItemList(self.taskId)
        while undoneTaskItem:
            if self.job['enable'] == 0:
                return
            if time.time() - tmStart > timeOut * 3600:
                jobMapper.updateJobTaskStatus(self.taskId, 5)
                return
            needUpdate = []
            for item in undoneTaskItem[:]:
                if self.job['enable'] == 0:
                    return
                try:
                    taskInfo = self.client.taskInfo(item['alistTaskId'])
                except Exception as e:
                    logger = logging.getLogger()
                    logger.exception(e)
                    eMsg = str(e)
                    if 'AList返回404错误' in eMsg:
                        eMsg = ("任务未找到。可能是您手动到AList中删除了复制任务；"
                                "或者Alist因手动/异常奔溃被重启，导致任务记录丢失_/_task not found."
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
        if 'enable' not in job:
            job['enable'] = 1
        if 'speed' not in job:
            job['speed'] = 0
        if 'method' not in job:
            job['method'] = 0
        job['id'] = job['id'] if 'id' in job else jobMapper.addJob(job)
        self.jobId = job['id']
        self.job = job
        self.scheduled = None
        self.scheduledJob = None
        self.jobDoing = False
        self.currentTaskId = None
        self.doByTime()

    def doJob(self):
        """
        执行作业
        :return:
        """
        while self.jobDoing:
            if self.job['enable'] == 0:
                return
            time.sleep(10)
        self.jobDoing = True
        taskId = None
        try:
            taskId = jobMapper.addJobTask({
                'jobId': self.jobId,
                'runTime': int(time.time())
            })
            self.currentTaskId = taskId
            JobTask(taskId, self.job)
        except Exception as e:
            logger = logging.getLogger()
            ste = str(e)
            if '_/_' in ste:
                sm = ste.split('_/_')
            else:
                sm = [ste, ste]
            errMsg = f"执行任务失败，原因为：{sm[0]}_/_Task execution failed due to: {sm[1]}"
            logger.error(errMsg)
            if taskId is not None:
                jobMapper.updateJobTaskStatus(taskId, 6, errMsg)
            logger.exception(e)
        finally:
            self.jobDoing = False
            self.currentTaskId = None

    def doManual(self):
        """
        手动执行作业
        :return:
        """
        if self.jobDoing:
            raise Exception("当前有任务执行中，请稍后再试_/_There is a task "
                            "currently being executed, please try again later")
        doJobThread = threading.Thread(target=self.doJob)
        doJobThread.start()

    def doByTime(self):
        params = {
            'func': self.doJob,
            'trigger': 'interval' if self.job['isCron'] == 0 else 'cron'
        }
        if self.job['isCron'] == 0:
            interval = self.job['interval']
            if interval is not None and str(interval).strip() != '':
                params['minutes'] = interval
            else:
                raise Exception("创建间隔型作业时，间隔必填")
        else:
            flag = 0
            for item in ['year', 'month', 'day', 'week', 'day_of_week', 'hour', 'minute', 'second', 'start_date',
                         'end_date']:
                if item in self.job and self.job[item] is not None and self.job[item] != '':
                    flag += 1
                    params[item] = self.job[item]
            if flag == 0:
                raise Exception("创建cron型任务时，至少有一项不为空")
        self.scheduled = BackgroundScheduler()
        self.scheduledJob = self.scheduled.add_job(**params)
        self.scheduled.start()
        if self.job['enable'] == 0:
            self.scheduledJob.pause()

    def resumeJob(self):
        """
        恢复作业
        :return:
        """
        if self.scheduledJob is None:
            raise Exception("作业不存在无法恢复，请删除后重新创建")
        else:
            jobMapper.updateJobEnable(self.jobId, 1)
            self.job['enable'] = 1
            self.scheduledJob.resume()

    def stopJob(self, remove=False, cancel=False):
        """
        停止作业（适用于修改enable）
        :param remove: 是否删除作业，否一般用于禁用作业
        :param cancel: 是否取消进行中的任务
        :return:
        """
        self.job['enable'] = 0
        if remove:
            if self.scheduled is not None:
                try:
                    self.scheduled.shutdown(wait=False)
                except Exception as e:
                    logger = logging.getLogger()
                    logger.warning(
                        f"停止定时任务失败，原因为：{str(e)}_/_Failed to stop the scheduled task due to: {str(e)}")
                    logger.exception(e)
                self.scheduled = None
        else:
            if self.scheduledJob is not None:
                try:
                    self.scheduledJob.pause()
                except Exception as e:
                    logger = logging.getLogger()
                    logger.warning(
                        f"禁用定时任务失败，原因为：{str(e)}_/_Failed to pause the scheduled task due to: {str(e)}")
                    logger.exception(e)
        self.jobDoing = False
        if self.currentTaskId is not None and cancel:
            undoneTaskItem = jobMapper.getUndoneJobTaskItemList(self.currentTaskId)
            cancelThread = threading.Thread(target=self.cancelUndoneJobTaskItem, args=(undoneTaskItem, remove))
            cancelThread.start()
        if not remove:
            jobMapper.updateJobEnable(self.jobId, 0)
            jobMapper.updateJobTaskStatusByStatusAndJobId(self.jobId)

    def cancelUndoneJobTaskItem(self, undoneTaskItem, remove=False):
        """
        取消未完成的作业任务子项
        """
        needUpdateList = []
        client = alistService.getClientById(self.job['alistId'])
        for item in undoneTaskItem:
            try:
                client.copyTaskCancel(item['alistTaskId'])
                if not remove:
                    needUpdateList.append({
                        'id': item['id'],
                        'status': 4,
                        'progress': 0,
                        'errMsg': None
                    })
            except Exception as e:
                logger = logging.getLogger()
                errMsg = f"取消任务过程中失败，原因为：{str(e)}_/_The task cancellation process failed due to:{str(e)}"
                logger.error(errMsg + f" job_task_item.id={item['id']}")
                logger.exception(e)
                if not remove:
                    needUpdateList.append({
                        'id': item['id'],
                        'status': 7,
                        'progress': 0,
                        'errMsg': errMsg
                    })
        if needUpdateList:
            jobMapper.updateJobTaskItemStatusByIdMany(needUpdateList)
