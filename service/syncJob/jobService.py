"""
@Author：dr34m
@Date  ：2024/7/9 17:17 
"""
from mapper import jobMapper
from service.syncJob import jobClient

# alist客户端列表，key为jId-{jobId},value为jobClient
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
    key = f'jId-{jobId}'
    global jobClientList
    if key in jobClientList:
        return jobClientList[key]
    job = jobMapper.getJobById(jobId)
    client = jobClient.JobClient(job)
    jobClientList[key] = client
    return client


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
    client = jobClient.JobClient(job)
    key = f"jId-{client.jobId}"
    global jobClientList
    jobClientList[key] = client


def removeJobClient(jobId):
    """
    删除作业
    :param jobId:
    :return:
    """
    client = getJobClientById(jobId)
    client.stopJob(remove=True)
    global jobClientList
    key = f'jId-{jobId}'
    del jobClientList[key]


def continueJob(jobId):
    """
    启用作业
    :param jobId:
    """
    client = getJobClientById(jobId)
    client.createJob()


def pauseJob(jobId):
    """
    禁用作业
    :param jobId:
    """
    client = getJobClientById(jobId)
    client.stopJob()


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
