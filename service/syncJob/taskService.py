import json
import logging
import threading

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
    job = jobMapper.getJobByTaskId(taskId)
    taskNum = getCuTaskNum(taskId)
    jobMapper.updateJobTaskNumMany([{
        'taskId': taskId,
        'taskNum': json.dumps(taskNum)
    }])
    statusName = G('task_status')[status]
    if notifyList:
        # 无需同步标识
        needNotSync = False
        if status == 2 and taskNum['allNum'] == 0:
            needNotSync = True
            statusName = G('task_status')[7]
        title = G('task_end_msg_title').format(statusName)
        content = G('task_end_msg_content').format(
            job['srcPath'], job['dstPath'].replace(':', '、'), taskNum['allNum'], taskNum['successNum'],
            taskNum['failNum'])
        if 3 < status < 6:
            content += G('task_end_msg_error').format(statusName)
        elif status == 6 and errMsg is not None:
            content += G('task_end_msg_error').format(errMsg)
        for notify in notifyList:
            try:
                notifyService.sendNotify(notify, title, content, needNotSync)
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
    # 需要更新任务数的列表（适配旧版本）
    needUpdateList = []
    for item in jobTaskList['dataList']:
        if item['taskNum']:
            taskNum = json.loads(item['taskNum'])
        else:
            taskNum = getCuTaskNum(item['id'])
            if item['status'] > 1:
                needUpdateList.append({
                    'taskId': item['id'],
                    'taskNum': json.dumps(taskNum)
                })
        for k, v in taskNum.items():
            item[k] = v
    if needUpdateList:
        updateThread = threading.Thread(target=jobMapper.updateJobTaskNumMany, args=(needUpdateList,))
        updateThread.start()
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
def countItem(srcPath, dstPath, fileName, srcModified, dstModified):
    return jobMapper.countItem(srcPath, dstPath, fileName, srcModified, dstModified)


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
