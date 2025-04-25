"""
@Author：dr34m
@Date  ：2024/7/9 17:17 
"""
import logging
import os
from hashlib import md5

from common.LNG import G
from mapper import jobMapper
from service.alist.alistService import getClientById
from service.syncJob import jobClient
from service.syncJob.jobUtills import alistAndLocalPathMatch

# alist客户端列表，key为jobId,value为jobClient
jobClientList = {}


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


    if job['encryptFlag'] != 0:
        client = getClientById(job['alistId'])
        # 加密和解密场景下，通过创建文件夹在另一端是否能能找到判断配置是否正确
        alistAndLocalPathMatch(job,client)

    client = jobClient.JobClient(job)
    jobMapper.updateJob(job)
    jobClientList[jobId] = client



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
