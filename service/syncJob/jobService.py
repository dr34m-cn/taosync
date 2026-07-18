"""
@Author：dr34m
@Date  ：2024/7/9 17:17 
"""
import logging

from common.LNG import G
from mapper import jobMapper
from service.storage import storageService
from service.syncJob import jobClient

# 作业客户端列表，key为jobId,value为jobClient
jobClientList = {}

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
    jobMapper.updateJobTaskStatusByStatus()
    jobList = jobMapper.getJobList()
    for item in jobList:
        try:
            logger.info(f"正在添加jobId为{item['id']}的任务")
            addJobClient(item, True)
        except Exception as e:
            logger.error(f"添加任务过程中报错")
            logger.exception(e)


def getJobClientById(jobId):
    """
    获取作业客户端
    :param jobId:
    :return:
    """
    jobId = int(jobId)
    global jobClientList
    if jobId in jobClientList:
        return jobClientList[jobId]
    job = jobMapper.getJobById(jobId)
    client = jobClient.JobClient(job)
    jobClientList[jobId] = client
    return client


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
        for dstPath in job['dstPath'].split(':'):
            engineId = job.get('alistId')
            pathsOverlap = (
                jobClient.virtualPathsOverlap(job['srcPath'], dstPath)
                if engineId is None
                else storageService.enginePathsOverlap(engineId, job['srcPath'], dstPath)
            )
            if pathsOverlap:
                raise Exception(G('source_target_overlap'))
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
    cleanJobInput(job)
    client = getJobClientById(jobId)
    if client.job['enable'] == 1 and client.job['isCron'] != 2:
        raise Exception(G('disable_then_edit'))
    clearSnapshot = any(client.job.get(key) != job.get(key) for key in SOURCE_SNAPSHOT_FIELDS)
    oldJob = client.job.copy()
    client.stopJob(remove=True)
    global jobClientList
    newClient = None
    try:
        newClient = jobClient.JobClient(job)
        jobMapper.updateJob(job, clearSourceSnapshot=clearSnapshot)
    except Exception:
        if newClient is not None:
            newClient.stopJob(remove=True)
        try:
            jobClientList[jobId] = jobClient.JobClient(oldJob)
        except Exception as restoreError:
            logging.getLogger().exception(restoreError)
        raise
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


def removeJobClient(jobId):
    """
    删除作业
    :param jobId:
    :return:
    """
    jobId = int(jobId)
    client = getJobClientById(jobId)
    client.stopJob(remove=True)
    jobMapper.deleteJob(jobId)
    global jobClientList
    del jobClientList[jobId]


def continueJob(jobId):
    """
    启用作业
    :param jobId:
    """
    client = getJobClientById(jobId)
    client.resumeJob()


def pauseJob(jobId):
    """
    禁用作业
    :param jobId:
    """
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
    return jobMapper.getJobList(req)


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
