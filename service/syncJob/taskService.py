from mapper import jobMapper


def updateJobTaskStatus(taskId, status, errMsg=None):
    """
    任务状态更新，任务完成后的操作
    :param taskId: 任务id
    :param status: 状态码：0-等待中，1-进行中，2-成功，3-完成（部分失败），4-因重启而中止，5-超时，6-失败
    :param errMsg: 错误消息
    :return:
    """
    jobMapper.updateJobTaskStatus(taskId, status, errMsg)


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
