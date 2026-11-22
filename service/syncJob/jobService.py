"""
@Author：dr34m
@Date  ：2024/7/9 17:17 
"""
import json
import logging
import threading

from common.LNG import G
from common.fileRetryReason import renderReason
from mapper import jobLinkMapper, jobMapper
from service.storage import storageService
from service.syncJob import jobClient, jobLinks, taskService
from service.syncJob.fileRetry import FileRetryTask

# 作业客户端列表，key为jobId,value为jobClient
jobClientList = {}
_configLock = threading.RLock()

MAX_SQLITE_INTEGER = 9223372036854775807
SOURCE_SNAPSHOT_FIELDS = jobMapper.SOURCE_SNAPSHOT_FIELDS


def normalizeFileSize(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise Exception(G('file_size_invalid'))
    if isinstance(value, int):
        result = value
    elif isinstance(value, float) and value.is_integer():
        result = int(value)
    elif isinstance(value, str) and value.isdigit():
        result = int(value)
    else:
        raise Exception(G('file_size_invalid'))
    if result < 0 or result > MAX_SQLITE_INTEGER:
        raise Exception(G('file_size_invalid'))
    return result


def normalizeSourceMode(value):
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int) and value in (0, 1):
        return value
    if isinstance(value, str) and value in ('0', '1'):
        return int(value)
    raise Exception(G('source_mode_invalid'))


def initJob():
    """
    用于启动后寻找任务，修改异常终止状态，启动启用的任务
    :return:
    """
    logger = logging.getLogger()
    try:
        removed = jobMapper.deleteOrphanRows()
        if removed:
            logger.info(f"已清理 {removed} 条无主任务记录")
    except Exception as e:
        logger.exception(e)
    jobMapper.updateJobTaskStatusByStatus()
    jobLinkMapper.recoverInterrupted()
    jobList = jobMapper.getJobList()
    for item in jobList:
        try:
            logger.info(f"正在添加jobId为{item['id']}的任务")
            addJobClient(item, True)
        except Exception as e:
            logger.error(f"添加任务过程中报错")
            logger.exception(e)

    jobLinks.startScheduler()


def getJobClientById(jobId):
    """
    获取作业客户端
    :param jobId:
    :return:
    """
    jobId = int(jobId)
    global jobClientList
    with _configLock:
        if jobId not in jobClientList:
            jobClientList[jobId] = jobClient.JobClient(jobMapper.getJobById(jobId))
        return jobClientList[jobId]


def cleanJobInput(job):
    """
    清洗输入的数据
    :param job: job对象
    :return:
    """
    if job['isCron'] == 2 and job['enable'] != 1:
        job['enable'] = 1
    for key, value in job.items():
        if type(value) == str:
            if value.strip() == '':
                job[key] = None
            else:
                job[key] = value.strip()
    if job['exclude'] is not None:
        job['exclude'] = ":".join([item.strip() for item in job['exclude'].split(':')])
    job.setdefault('minFileSize', None)
    job.setdefault('maxFileSize', None)
    job.setdefault('sourceMode', 0)
    job['minFileSize'] = normalizeFileSize(job['minFileSize'])
    job['maxFileSize'] = normalizeFileSize(job['maxFileSize'])
    job['sourceMode'] = normalizeSourceMode(job['sourceMode'])
    if job.get('srcPath') and job.get('dstPath'):
        engineId = job.get('alistId')
        overlaps = jobClient.virtualPathsOverlap if engineId is None else (
            lambda a, b: storageService.enginePathsOverlap(engineId, a, b))
        jobClient.validateJobPaths(job['srcPath'], job['dstPath'].split(':'), overlaps)
    if (job['minFileSize'] is not None
            and job['maxFileSize'] is not None
            and job['minFileSize'] > job['maxFileSize']):
        raise Exception(G('file_size_range_invalid'))


def addJobClient(job, isInit=False):
    """
    新增作业客户端
    :param isInit: 是否是初始化过程
    :param job: {
        enable: 1,
        srcPath: '',
        dstPath: '',
        alistId: null,
        speed: 0,
        method: 0,
        interval: 60
    }
    :return:
    """
    cleanJobInput(job)
    client = jobClient.JobClient(job, isInit)
    global jobClientList
    jobClientList[int(client.jobId)] = client


def editJobClient(job):
    """
    编辑作业客户端
    :param job: {
        id: 1,
        enable: 1,
        srcPath: '',
        dstPath: '',
        alistId: null,
        speed: 0,
        method: 0,
        interval: 60
    }
    """
    jobId = int(job['id'])
    with _configLock:
        client = getJobClientById(jobId)
        if not jobClient.acquireRun(client.runLock):
            raise Exception(G('job_running_cannot_edit'))
        try:
            cleanJobInput(job)
            _replaceIdleClient(jobId, client, job)
        finally:
            client.runLock.release()


def _replaceIdleClient(jobId, client, job):
    clearSnapshot = any(client.job.get(key) != job.get(key) for key in SOURCE_SNAPSHOT_FIELDS)
    # Both callbacks share the held run lock. Keep the old trigger (and its
    # next fire time) until the replacement configuration is persisted.
    newClient = jobClient.JobClient(job, runLock=client.runLock)
    try:
        jobMapper.updateJob(job, clearSourceSnapshot=clearSnapshot)
    except Exception:
        newClient.stopJob(remove=True)
        raise
    client.stopJob(remove=True)
    jobClientList[jobId] = newClient


def doAllJobManual():
    """
    手动执行所有未禁用的作业
    :return:
    """
    jobList = jobMapper.getEnableJobList()
    if not jobList:
        raise Exception(G('no_job_for_run'))
    for jobItem in jobList:
        client = getJobClientById(jobItem['id'])
        if client.job['enable'] == 1:
            client.doManual()


def pauseAllJob():
    """Disable every scheduled job; manual-only jobs cannot be disabled."""
    for job in jobMapper.getJobList():
        if job.get('isCron') == 2 or job.get('enable') != 1:
            continue
        pauseJob(job['id'])


def continueAllJob():
    """Enable every scheduled job that is currently disabled."""
    for job in jobMapper.getJobList():
        if job.get('isCron') == 2 or job.get('enable') == 1:
            continue
        continueJob(job['id'])


def doJobManual(jobId):
    """
    手动执行作业
    :param jobId:
    :return:
    """
    client = getJobClientById(jobId)
    if client.job['enable'] != 1:
        raise Exception(G('disabled_job_cannot_run'))
    client.doManual()


def launchLinkedJob(jobId):
    with _configLock:
        client = getJobClientById(jobId)
        if client.job['enable'] != 1 or client.removed:
            raise ValueError('link_target_disabled')
        reason = jobClient.tryAcquireRun(client.runLock)
        if reason == 'busy':
            return 'skipped'
        if reason:
            raise ValueError('link_updating')
    if not client.doJob(lockAcquired=True):
        raise ValueError('link_start_failed')
    return 'executed'


def retryFile(taskId, itemId):
    if itemId is None:
        raise ValueError(G('file_retry_ineligible'))
    return retryFiles(taskId, itemId)


def retryFiles(taskId, itemId=None):
    source = jobMapper.getJobTaskById(taskId)
    with _configLock:
        client = getJobClientById(source['jobId'])
        if client.removed or client.job['enable'] != 1:
            raise ValueError(G('disabled_job_cannot_run'))
        task = client.currentJobTask
        if isinstance(task, FileRetryTask) and not task.breakFlag:
            retryId, items = jobMapper.claimFileRetries(taskId, client.jobId, itemId, task.taskId)
            task.enqueue(items)
            return {'id': retryId, 'count': len(items)}
        if not jobClient.acquireRun(client.runLock):
            raise ValueError(G('job_running'))
        retryId = None
        try:
            retryId, items = jobMapper.claimFileRetries(taskId, client.jobId, itemId)
            if not items:
                client.finishRun()
                return {'id': None, 'count': 0}
            task = FileRetryTask(retryId, client, _configLock)
            task.enqueue(items)
            client.currentJobTask = task
            client.jobDoing = True
            task.start()
            return {'id': retryId, 'count': len(items)}
        except Exception as exc:
            try:
                if retryId is not None:
                    jobMapper.updateJobTaskStatus(retryId, 6, str(exc))
            finally:
                client.finishRun()
            raise


def getTaskDetails(req):
    result = taskService.getTaskItemList(req)
    rows = result['dataList'] if isinstance(result, dict) else result
    ids = {row['retryTaskId'] for row in rows if row.get('retryTaskId')}
    if ids:
        retries = {run['id']: run for run in jobMapper.getFileRetryResults(ids)}
        for row in rows:
            run = retries.get(row.get('retryTaskId'))
            if run is None:
                continue
            retry = dict(run)
            if row.get('lastRetryStatus') is not None:
                retry.update(status=row['lastRetryStatus'], errMsg=row['lastRetryError'],
                             retryReason=row['lastRetryReason'])
            elif run['status'] < 2:
                client = jobClientList.get(run['jobId'])
                task = client.currentJobTask if client else None
                if isinstance(task, FileRetryTask) and task.taskId == run['id']:
                    retry.update(task.retryProgress(row['id']), errMsg=None, retryReason=None)
            row['retry'] = renderReason(retry)
    return result


def removeJobClient(jobId):
    """
    删除作业
    :param jobId:
    :return:
    """
    jobId = int(jobId)
    with _configLock:
        client = getJobClientById(jobId)
        # 先标记，运行中的任务结束时据此跳过入库并清理自身记录
        client.removed = True
        client.stopJob(remove=True)
        jobMapper.deleteJob(jobId)
        del jobClientList[jobId]


def continueJob(jobId):
    """
    启用作业
    :param jobId:
    """
    with _configLock:
        getJobClientById(jobId).resumeJob()


def pauseJob(jobId):
    """
    禁用作业
    :param jobId:
    """
    with _configLock:
        client = getJobClientById(jobId)
        if client.job['isCron'] == 2:
            raise Exception(G('cannot_disable_manual_job'))
        client.stopJob()


def abortJob(jobId):
    """
    中止作业
    :param jobId:
    :return:
    """
    client = getJobClientById(jobId)
    client.abortJob()


def getJobList(req):
    """
    作业列表
    :param req: {
        'pageSize': 1,
        'pageNum': 2
    }
    :return:
    """
    result = jobMapper.getJobList(req)
    rows = result.get('dataList', result) if isinstance(result, dict) else result
    latestTasks = {
        task['jobId']: task for task in jobMapper.getLatestJobTaskList(
            [row['id'] for row in rows]
        )
    }
    for row in rows:
        task = latestTasks.get(row['id'])
        if task is None:
            row['lastTask'] = None
            continue
        taskNum = {}
        if task.get('taskNum'):
            try:
                parsed = json.loads(task['taskNum'])
                if isinstance(parsed, dict):
                    taskNum = parsed
            except (TypeError, ValueError):
                pass
        task['allNum'] = taskNum.get('allNum', task.get('itemAllNum') or 0)
        task['successNum'] = taskNum.get('successNum', task.get('itemSuccessNum') or 0)
        task['failNum'] = taskNum.get('failNum', task.get('itemFailNum') or 0)
        task['otherNum'] = taskNum.get('otherNum', task.get('itemOtherNum') or 0)
        task['duration'] = taskNum.get('duration')
        task.pop('taskNum', None)
        task.pop('itemAllNum', None)
        task.pop('itemSuccessNum', None)
        task.pop('itemFailNum', None)
        task.pop('itemOtherNum', None)
        row['lastTask'] = renderReason(task)
    return result


def getJobCurrent(jobId, status=None):
    """
    获取当前作业正在执行中的任务的详情
    :param jobId:
    :param status: 状态
    :return:
    """
    client = getJobClientById(int(jobId))
    taskClient = client.currentJobTask
    if taskClient is not None:
        if status is None:
            return taskClient.getCurrent()
        else:
            return taskClient.getCurrentByStatus(int(status))
    return None
