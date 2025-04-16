"""
@Author：dr34m
@Date  ：2024/7/11 12:14 
"""
import json
import logging
import threading
import time

from apscheduler.schedulers.background import BackgroundScheduler

from common.LNG import G
from common.config import getConfig
from mapper import jobMapper
from service.alist import alistSync, alistService
from service.syncJob import taskService


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
        cfg = getConfig()
        timeOut = cfg['server']['timeout']
        while undoneTaskItem:
            if self.job['enable'] == 0:
                return
            if time.time() - tmStart > timeOut * 3600:
                taskService.updateJobTaskStatus(self.taskId, 5)
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
                    if '404' in eMsg:
                        eMsg = (G('task_may_delete'))
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
        所有任务完成后，最终更新任务状态
        """
        unSuccessTaskItem = jobMapper.getUnSuccessJobTaskItemList(self.taskId)
        status = 2 if not unSuccessTaskItem else 3
        taskService.updateJobTaskStatus(self.taskId, status)


class JobClient:
    def __init__(self, job, isInit=False):
        """
        初始化job
        :param job: {id(新增时不需要), enable, srcPath, dstPath, alistId, speed, method, interval, exclude, cron相关}
        """
        addJobId = 0
        if 'enable' not in job:
            job['enable'] = 1
        if 'speed' not in job:
            job['speed'] = 0
        if 'method' not in job:
            job['method'] = 0
        if 'id' not in job:
            addJobId = jobMapper.addJob(job)
            job = jobMapper.getJobById(addJobId)
        self.jobId = job['id']
        self.job = job
        self.scheduled = None
        self.scheduledJob = None
        self.jobDoing = False
        self.currentTaskId = None
        try:
            self.doByTime()
        except Exception as e:
            if isInit or addJobId != 0:
                # 仅在初始化和新增任务时删除错误的任务
                logger = logging.getLogger()
                logger.error(f"任务启动过程中报错，将自动删除任务，任务为{json.dumps(self.job)}")
                jobMapper.deleteJob(self.jobId)
            raise e

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
            errMsg = G('do_job_err').format(str(e))
            logger.error(errMsg)
            if taskId is not None:
                taskService.updateJobTaskStatus(taskId, 6, errMsg)
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
            raise Exception(G('job_running'))
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
                raise Exception(G('interval_lost'))
        elif self.job['isCron'] == 1:
            flag = 0
            for item in ['year', 'month', 'day', 'week', 'day_of_week', 'hour', 'minute', 'second', 'start_date',
                         'end_date']:
                if item in self.job and self.job[item] is not None and self.job[item] != '':
                    flag += 1
                    params[item] = self.job[item]
            if flag == 0:
                raise Exception(G('cron_lost'))
        else:
            return
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
            raise Exception(G('cannot_resume_lost_job'))
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
                    logger.warning(G('stop_fail').format(str(e)))
                    logger.exception(e)
                self.scheduled = None
        else:
            if self.scheduledJob is not None:
                try:
                    self.scheduledJob.pause()
                except Exception as e:
                    logger = logging.getLogger()
                    logger.warning(G('disable_fail').format(str(e)))
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
                errMsg = G('cancel_fail').format(str(e))
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
