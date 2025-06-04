"""
@Author：dr34m
@Date  ：2024/7/11 12:14 
"""
import itertools
import json
import logging
import threading
import time
from collections import defaultdict

from apscheduler.schedulers.background import BackgroundScheduler
from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

from common.LNG import G
from mapper import jobMapper
from service.alist import alistService
from service.syncJob import taskService


class CopyItem:
    def __init__(self, srcPath, dstPath, fileName, fileSize, method, jobTask):
        self.jobTask = jobTask
        self.alistClient = self.jobTask.alistClient
        self.taskId = self.jobTask.taskId
        self.srcPath = srcPath
        self.dstPath = dstPath
        self.fileName = fileName
        self.fileSize = fileSize
        self.copyType = 0 if method < 2 else 2
        self.alistTaskId = None
        self.status = 0
        self.progress = 0.0
        self.errMsg = None
        self.createTime = int(time.time())
        self.doingKey = None

    def doIt(self):
        try:
            self.alistTaskId = self.alistClient.copyFile(self.srcPath, self.dstPath, self.fileName)
        except Exception as e:
            self.errMsg = str(e)
            self.status = 7
        else:
            if self.alistTaskId is None:
                self.status = 2
            else:
                self.checkAndGetStatus()
        self.endIt()

    def checkAndGetStatus(self):
        """
        不断检查状态并更新
        :return:
        """
        while True:
            cuTime = time.time()
            time.sleep(0.29 if cuTime - self.jobTask.lastWatching < 3 else 2.93)
            try:
                taskInfo = self.alistClient.taskInfo(self.alistTaskId)
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
            if taskInfo['state'] == self.status and taskInfo['progress'] == self.progress:
                continue
            self.status = taskInfo['state']
            self.progress = taskInfo['progress']
            self.errMsg = taskInfo['error'] if taskInfo['error'] else None
            # 删除结束的任务
            if taskInfo['state'] in [2, 4, 7]:
                try:
                    self.alistClient.copyTaskDelete(self.alistTaskId)
                    break
                except Exception:
                    break

    def endIt(self):
        if self.copyType == 2 and self.status == 2:
            try:
                self.alistClient.deleteFile(self.srcPath, [self.fileName])
            except Exception as e:
                self.status = 7
                self.errMsg = G('copy_success_but_delete_fail').format(str(e))
        self.jobTask.copyHook(self.srcPath, self.dstPath, self.fileName, self.fileSize, self.alistTaskId, self.status,
                              errMsg=self.errMsg, copyType=self.copyType, createTime=self.createTime)
        del self.jobTask.doing[self.doingKey]


class JobTask:
    def __init__(self, taskId, job):
        """
        作业任务类
        :param taskId: 任务id
        :param job: 作业信息
        """
        self.taskId = taskId
        self.job = job
        self.alistClient = alistService.getClientById(self.job['alistId'])
        self.createTime = time.time()
        # 已完成（包含成功或者失败）
        self.finish = []
        # 已经提交到alist的任务
        self.doing = {}
        # 等待提交到alist的任务
        self.waiting = []
        # 上次查看详情的时间戳，低于2秒表示正在看，在看则快速检查状态，否则低速检查以节约开销
        self.lastWatching = 0.0
        # 队列序号，用作复制任务的doingKey
        self.queueNum = 0
        # sync全部任务加入队列标识
        self.scanFinish = False
        syncThread = threading.Thread(target=self.sync)
        syncThread.start()
        self.currentTasks = {}
        self.taskSubmit()
        jobMapper.addJobTaskItemMany(self.finish)
        self.updateTaskStatus()

    def getCurrent(self, status):
        """
        总结并返回详情（高实时性）
        {
            'srcPath': 来源目录,
            'dstPath': 目标目录,
            'fileName': 文件名,
            'fileSize': 文件大小,
            'status': 状态,
            'type': 方式，0-复制（对于目录则是创建），1-删除，2-移动,
            'progress': 进度,
            'errMsg': 错误信息,
            'createTime': 创建时间
        }
        :return: {
            0: [],
            1: [],
            ...
        }
        """
        self.lastWatching = time.time()
        waits = [{
            'srcPath': waitItem.srcPath,
            'dstPath': waitItem.dstPath,
            'isPath': 0,
            'fileName': waitItem.fileName,
            'fileSize': waitItem.fileSize,
            'status': waitItem.status,
            'type': waitItem.copyType,
            'progress': waitItem.progress,
            'errMsg': waitItem.errMsg,
            'createTime': waitItem.createTime
        } for waitItem in self.waiting]
        dos = [{
            'srcPath': doItem.srcPath,
            'dstPath': doItem.dstPath,
            'isPath': 0,
            'fileName': doItem.fileName,
            'fileSize': doItem.fileSize,
            'status': doItem.status,
            'type': doItem.copyType,
            'progress': doItem.progress,
            'errMsg': doItem.errMsg,
            'createTime': doItem.createTime
        } for doItem in self.doing.values()]
        allTask = list(itertools.chain(waits, dos, self.doing))
        keyValSpace = {
            'wait': 0,
            'running': 1,
            'success': 2,
            'fail': 7,
            'other': -1
        }
        currentTasks = {}
        for val in keyValSpace.values():
            currentTasks[val] = []
        # 其他类型数组
        otk = []
        otkStatus = [3, 4, 5, 6, 8, 9]
        grouped = defaultdict(list)
        for taskItem in allTask:
            grouped[taskItem['status']].append(taskItem)
        for status, tasks in grouped.items():
            tasks.sort(key=lambda x: x['createTime'])
            if status in otkStatus:
                otk.extend(tasks)
            else:
                currentTasks[status] = tasks
        currentTasks[-1] = otk
        self.currentTasks = currentTasks
        result = {
            'scanFinish': self.scanFinish,
            'doingTask': currentTasks[1],
            'createTime': int(self.createTime),
            'duration': int(self.lastWatching - self.createTime),
            'num': {},
            'size': {}
        }
        for key, val in keyValSpace.items():
            result['num'][key] = len(currentTasks[val])
            result['size'][key] = sum(
                item['fileSize'] for item in currentTasks[val] if item['fileSize'] is not None and item['type'] != 1)
        return result

    def getCurrentByStatus(self, status):
        return self.currentTasks[status]

    def taskSubmit(self):
        """
        队列检验与提交
        :return:
        """
        while True:
            time.sleep(0.5)
            doingNums = len(self.doing.keys())
            waitingNums = len(self.waiting)
            if not self.scanFinish or doingNums != 0 or waitingNums != 0:
                while doingNums < 20:
                    if waitingNums == 0:
                        break
                    else:
                        self.queueNum += 1
                        self.doing[self.queueNum] = self.waiting.pop(0)
                        self.doing[self.queueNum].doingKey = self.queueNum
                        self.doing[self.queueNum].doIt()
                        doingNums = len(self.doing.keys())
                        waitingNums = len(self.waiting)
            else:
                break

    def copyHook(self, srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None, isPath=0,
                 copyType=0, createTime=int(time.time())):
        """
        复制文件回调
        :param srcPath: 来源目录
        :param dstPath: 目标目录
        :param name: 文件名
        :param size: 文件大小
        :param alistTaskId: alist任务id
        :param status: 0-等待中，1-运行中，2-成功，3-取消中，4-已取消，5-出错（将重试），6-失败中，
                        7-已失败，8-等待重试中，9-等待重试回调执行中，10-目录扫描失败，11-目录创建失败
        :param errMsg: 错误信息
        :param isPath: 是否是目录，0-文件，1-目录
        :param copyType: 0-复制，2-移动
        :param createTime:
        """
        self.finish.append({
            'taskId': self.taskId,
            'srcPath': srcPath,
            'dstPath': dstPath,
            'isPath': isPath,
            'fileName': name,
            'fileSize': size,
            'type': copyType,
            'alistTaskId': alistTaskId,
            'status': status,
            'errMsg': errMsg,
            'createTime': createTime
        })

    def delHook(self, dstPath, name, size, status=2, errMsg=None, isPath=0):
        """
        删除文件回调
        :param dstPath: 目标目录
        :param name: 文件名
        :param size: 文件大小
        :param status: 2-成功、7-失败
        :param errMsg: 错误信息
        :param isPath: 是否是目录，0-文件，1-目录
        """
        self.finish.append({
            'taskId': self.taskId,
            'srcPath': None,
            'dstPath': dstPath,
            'isPath': isPath,
            'fileName': name,
            'fileSize': size,
            'type': 1,
            'alistTaskId': None,
            'status': status,
            'errMsg': errMsg
        })

    def sync(self):
        """
        同步方法
        """
        srcPath = self.job['srcPath']
        jobExclude = self.job['exclude']
        spec = None
        if jobExclude is not None:
            spec = PathSpec.from_lines(GitWildMatchPattern, jobExclude.split(':'))
        if not srcPath.endswith('/'):
            srcPath = srcPath + '/'
        dstPathList = self.job['dstPath'].split(':')
        i = 0
        for dstItem in dstPathList:
            i += 1
            self.syncWithHave(srcPath, dstItem, spec, srcPath, dstItem, i == 1)
        self.scanFinish = True

    def copyFile(self, srcPath, dstPath, fileName, fileSize):
        """
        复制文件
        vm.job['speed']: 速度，0-标准，1-快速，2-低速
        vm.job['method']: 0-仅新增，1-全同步，2-移动模式
        vm.job['copyHook']: 复制文件回调，（srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None, isPath=0）
        vm.job['delHook']: 删除文件回调，（dstPath, name, size, status=2:2-成功、7-失败, errMsg=None, isPath=0）
        :param srcPath: 源目录
        :param dstPath: 目标目录
        :param fileName: 文件名
        :param fileSize: 文件大小
        :return:
        """
        if self.job is None or self.job['enable'] == 0:
            return
        copyItem = CopyItem(srcPath, dstPath, fileName, fileSize, self.job['method'], self)
        self.waiting.append(copyItem)

    def delFile(self, path, fileName, size):
        """
        删除文件（或目录）
        vm.job['speed']: 速度，0-标准，1-快速，2-低速
        vm.job['method']: 0-仅新增，1-全同步，2-移动模式
        vm.job['copyHook']: 复制文件回调，（srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None, isPath=0）
        vm.job['delHook']: 删除文件回调，（dstPath, name, size, status=2:2-成功、7-失败, errMsg=None, isPath=0）
        :param path: 所在路径
        :param fileName: 文件名（或目录名）
        :param size: 大小（文件）或空对象（目录）
        :return:
        """
        if self.job is None or self.job['enable'] == 0:
            return
        isPath = fileName.endswith('/')
        status = 2
        errMsg = None
        try:
            self.alistClient.deleteFile(path, fileName if not isPath else fileName[:-1])
        except Exception as e:
            status = 7
            errMsg = str(e)
        self.delHook(path, fileName, None if isPath else size, status, errMsg, isPath)

    def listDir(self, path, firstDst, spec, rootPath, isSrc=True):
        """
        列出目录
        :param path:
        :param firstDst:
        :param spec:
        :param rootPath:
        :param isSrc:
        :return:
        """
        speed = self.job['speed']
        if isSrc:
            speed = 1 if not firstDst else (0 if self.job['speed'] < 2 else 2)
        try:
            return self.alistClient.fileListApi(path, speed, spec, rootPath)
        except Exception as e:
            logger = logging.getLogger()
            errMsg = G('scan_error').format(G('src' if isSrc else 'dst'), str(e))
            logger.error(errMsg)
            logger.exception(e)
            self.copyHook(path if isSrc else None, None if isSrc else path, None, None, status=7, errMsg=errMsg,
                          isPath=1)
            raise e

    def syncWithHave(self, srcPath, dstPath, spec, srcRootPath, dstRootPath, firstDst):
        """
        扫描并同步-目标目录存在目录（意味着要继续扫描目标目录）
        :param vm: 上级上下文，vm.taskItemList将包含所有任务，vm.job['enable']决定是否继续
        :param srcPath: 来源路径，以/结尾
        :param dstPath: 目标路径，以/结尾
        :param spec: 排除项规则
        :param srcRootPath: 来源目录根目录，以/结尾
        :param dstRootPath: 目标目录根目录，以/结尾
        :param firstDst: 是否是第一个目标目录（如果是，将完整扫描源目录，否则使用缓存扫描源目录）
        :return:
        """
        if self.job is None or self.job['enable'] == 0:
            return
        try:
            srcFiles = self.listDir(srcPath, firstDst, spec, srcRootPath)
            dstFiles = self.listDir(dstPath, firstDst, spec, dstRootPath, False)
        except Exception:
            # 已在listDir做出日志打印等操作，此处啥都不用做
            return
        for key in srcFiles.keys():
            # 如果是文件
            if not key.endswith('/'):
                # 目标目录没有这个文件或文件大小不匹配(即需要同步)
                if key not in dstFiles or dstFiles[key] != srcFiles[key]:
                    self.copyFile(srcPath, dstPath, key, srcFiles[key])
            # 如果是目录
            else:
                # 目标目录没有这个目录
                if key not in dstFiles:
                    self.syncWithOutHave(srcPath + key, dstPath + key, spec, srcRootPath, dstRootPath,
                                         firstDst)
                # 目标目录有这个目录，继续递归
                else:
                    self.syncWithHave(srcPath + key, dstPath + key, spec, srcRootPath, dstRootPath,
                                      firstDst)
        if self.job['method'] == 1:
            for dstKey in dstFiles.keys():
                if dstKey not in srcFiles:
                    self.delFile(dstPath, dstKey, dstFiles[dstKey])

    def syncWithOutHave(self, srcPath, dstPath, spec, srcRootPath, dstRootPath, firstDst):
        """
        扫描并同步-目标目录为空
        :param vm: 上级上下文，vm.taskItemList将包含所有任务，vm.job['enable']决定是否继续
        :param srcPath: 来源路径，以/结尾
        :param dstPath: 目标路径，以/结尾
        :param spec:
        :param srcRootPath:
        :param dstRootPath:
        :param firstDst:
        :return:
        """
        if self.job is None or self.job['enable'] == 0:
            return
        status = 2
        errMsg = None
        try:
            self.alistClient.mkdir(dstPath)
        except Exception as e:
            status = 7
            errMsg = str(e)
        # 目录回调
        self.copyHook(srcPath, dstPath, None, None, status=status, errMsg=errMsg, isPath=1)
        if status != 2:
            return
        try:
            srcFiles = self.listDir(srcPath, firstDst, spec, srcRootPath)
        except Exception:
            # 已在listDir做出日志打印等操作，此处啥都不用做
            return
        for key in srcFiles.keys():
            if key.endswith('/'):
                self.syncWithOutHave(srcPath + key, dstPath + key, spec, srcRootPath, dstRootPath, firstDst)
            else:
                self.copyFile(srcPath, dstPath, key, srcFiles[key])

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
        # 正在执行中的作业信息；仅在内存中，不入库，高速读写；执行完毕后批量入库，如果遇到异常终止，不会补偿入库
        # 单项结构 {
        #   'taskId':   所属任务id
        #   'alistTaskId': alist任务id
        #   'srcPath':  来源路径
        #   'dstPath':  目标路径
        #   'fileName': 文件名或者文件目录名
        #   'fileSize': 文件大小
        #   'status':   状态 0-等待中，1-运行中，2-成功，3-取消中，4-已取消，5-出错（将重试），
        #               6-失败中，7-已失败，8-等待重试中，9-等待重试回调执行中
        #   'progress': 进度
        #   'errMsg':   失败原因
        # }
        self.currentJobTask = None
        try:
            self.doByTime()
        except Exception as e:
            if isInit or addJobId != 0:
                # 仅在初始化和新增任务时删除错误的任务
                logger = logging.getLogger()
                logger.error(G('del_job_course_error').format(json.dumps(self.job)))
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
            self.currentJobTask = JobTask(taskId, self.job)
        except Exception as e:
            logger = logging.getLogger()
            errMsg = G('do_job_err').format(str(e))
            logger.error(errMsg)
            if taskId is not None:
                taskService.updateJobTaskStatus(taskId, 6, errMsg)
            logger.exception(e)
        finally:
            self.jobDoing = False
            self.currentJobTask = None

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

    def stopJob(self, remove=False):
        """
        停止作业（适用于修改enable）
        :param remove: 是否删除作业，否一般用于禁用作业
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
        if not remove:
            jobMapper.updateJobEnable(self.jobId, 0)
            jobMapper.updateJobTaskStatusByStatusAndJobId(self.jobId)
