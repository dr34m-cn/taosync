import logging

from common.LNG import G
from mapper import jobMapper
from service.notify import notifyService


def updateJobTaskStatus(taskId, status, errMsg=None):
    """
    任务状态更新，任务完成后的操作，此处status一定大于1
    :param taskId: 任务id
    :param status: 状态码：0-等待中，1-进行中，2-成功，3-完成（部分失败），4-因重启而中止，5-超时，6-失败
    :param errMsg: 错误消息
    :return:
    """
    jobMapper.updateJobTaskStatus(taskId, status, errMsg)
    notifyList = notifyService.getNotifyList(True)
    if notifyList:
        job = jobMapper.getJobByTaskId(taskId)
        taskNum = getCuTaskNum(taskId)
        statusName = G('task_status')[status]
        if status == 2 and taskNum['allNum'] == 0:
            statusName = G('task_status')[7]
        title = G('task_end_msg_title').format(statusName)
        content = G('task_end_msg_content').format(
            job['srcPath'], job['dstPath'].replace(':', '、'), taskNum['allNum'], taskNum['successNum'], taskNum['failNum'])
        if 3 < status < 6:
            content += G('task_end_msg_error').format(statusName)
        elif status == 6 and errMsg is not None:
            content += G('task_end_msg_error').format(errMsg)
        for notify in notifyList:
            try:
                notifyService.sendNotify(notify, title, content)
            except Exception as e:
                logger = logging.getLogger()
                logger.error(G('notify_error').format(str(e)))


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
        taskNum = getCuTaskNum(item['id'])
        for k, v in taskNum.items():
            item[k] = v
    return jobTaskList


def getCuTaskNum(taskId):
    return {
        'waitNum': jobMapper.getJobTaskCountByStatus(taskId, 0),
        'runningNum': jobMapper.getJobTaskCountByStatus(taskId, 1),
        'successNum': jobMapper.getJobTaskCountByStatus(taskId, 2),
        'failNum': jobMapper.getJobTaskCountByStatus(taskId, 7),
        'otherNum': jobMapper.getJobTaskCountByOther(taskId),
        'allNum': jobMapper.getJobTaskCountByAll(taskId)
    }


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
