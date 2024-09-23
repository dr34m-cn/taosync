"""
@Author：dr34m
@Date  ：2024/7/9 17:17 
"""
from common.LNG import G
from mapper import jobMapper
from service.syncJob import jobClient

# alist客户端列表，key为jobId,value为jobClient
jobClientList = {}


def initJob():
    """
    用于启动后寻找任务，修改异常终止状态，启动启用的任务
    :return:
    """
    jobMapper.updateJobTaskStatusByStatus()
    jobList = jobMapper.getJobList()
    for item in jobList:
        addJobClient(item)


def getJobClientById(jobId):
    """
    获取作业客户端
    :param jobId:
    :return:
    """
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
        job['exclude'] = [item.strip() for item in job['exclude'].split(':')]


def addJobClient(job):
    """
    新增作业客户端
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
    client = jobClient.JobClient(job)
    global jobClientList
    jobClientList[client.jobId] = client


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
    jobId = job['id']
    cleanJobInput(job)
    client = getJobClientById(jobId)
    if client.job['enable'] == 1 and client.job['isCron'] != 2:
        raise Exception(G('disable_then_edit'))
    client.stopJob(remove=True)
    global jobClientList
    del jobClientList[jobId]
    jobMapper.updateJob(job)
    client = jobClient.JobClient(job)
    jobClientList[jobId] = client


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


def removeJobClient(jobId, cancel=False):
    """
    删除作业
    :param jobId:
    :param cancel: 是否取消进行中的任务
    :return:
    """
    client = getJobClientById(jobId)
    client.stopJob(remove=True, cancel=cancel)
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


def pauseJob(jobId, cancel=False):
    """
    禁用作业
    :param jobId:
    :param cancel: 是否取消进行中的任务
    """
    client = getJobClientById(jobId)
    if client.job['isCron'] == 2:
        raise Exception(G('cannot_disable_manual_job'))
    client.stopJob(cancel=cancel)


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


def getTaskList(req):
    """
    任务列表
    :param req: {
        'id': 1,
        'pageSize': 1,
        'pageNum': 2
    }
    :return: {id, jobId, status, runTime, createTime}
    """
    jobTaskList = jobMapper.getJobTaskList(req)
    for item in jobTaskList['dataList']:
        taskId = item['id']
        item['waitNum'] = jobMapper.getJobTaskCountByStatus(taskId, 0)
        item['runningNum'] = jobMapper.getJobTaskCountByStatus(taskId, 1)
        item['successNum'] = jobMapper.getJobTaskCountByStatus(taskId, 2)
        item['failNum'] = jobMapper.getJobTaskCountByStatus(taskId, 7)
        item['otherNum'] = jobMapper.getJobTaskCountByOther(taskId)
        item['allNum'] = jobMapper.getJobTaskCountByAll(taskId)
    return jobTaskList


def removeTask(taskId):
    """
    删除任务
    :param taskId:
    :return:
    """
    jobMapper.deleteJobTaskByTaskId(taskId)


def getTaskItemList(req):
    """
    任务详情列表
    :param req: {
        'taskId': 1,
        'pageSize': 1,
        'pageNum': 2
    }
    :return:
    """
    return jobMapper.getJobTaskItemList(req)
