"""
@Author：dr34m
@Date  ：2024/7/9 17:18 
"""
from common import sqlBase


def getJobList(params=None):
    # 作业列表
    return sqlBase.fetchall_to_page("select * from job order by createTime desc ", params)


def getJobById(jobId):
    # 作业详情
    rst = sqlBase.fetchall_to_table("select * from job where id=?", (jobId,))
    if rst:
        return rst[0]
    else:
        raise Exception("未找到作业，可能已经被删除_/_The job was not found and may have been deleted")


def addJob(job):
    # 新增作业
    return sqlBase.execute_insert("insert into job (enable, srcPath, dstPath, alistId, speed, method, interval"
                                  ",isCron, year, month, day, week, day_of_week, hour, minute, second, "
                                  "start_date, end_date) "
                                  "VALUES (:enable, :srcPath, :dstPath, :alistId, :speed, :method, :interval, "
                                  ":isCron, :year, :month, :day, :week, :day_of_week, :hour, :minute, :second, "
                                  ":start_date, :end_date)", job)


def updateJob(job):
    sqlBase.execute_update("update job set enable=:enable, srcPath=:srcPath, dstPath=:dstPath, alistId=:alistId, "
                           "speed=:speed, method=:method, interval=:interval, isCron=:isCron, year=:year, "
                           "month=:month, day=:day, week=:week, day_of_week=:day_of_week, hour=:hour, minute=:minute, "
                           "second=:second, start_date=:start_date, end_date=:end_date where id=:id", job)


def updateJobEnable(jobId, enable):
    # 更新作业执行状态
    sqlBase.execute_update("update job set enable = ? where id = ?", (enable, jobId))


def deleteJob(jobId):
    sqlBase.execute_update("delete from job_task_item where "
                           "taskId in (select id from job_task where jobId=?)", (jobId,))
    sqlBase.execute_update("delete from job_task where jobId=?", (jobId,))
    sqlBase.execute_update("delete from job where id=?", (jobId,))


def getJobTaskList(req):
    return sqlBase.fetchall_to_page("select * from job_task where jobId=:id order by createTime desc ", req)


def getJobTaskCountByStatus(taskId, status):
    return sqlBase.fetch_first_val("select count(id) from job_task_item where status=? "
                                   "and taskId=?", (status, taskId))


def getJobTaskCountByOther(taskId):
    return sqlBase.fetch_first_val("select count(id) from job_task_item where "
                                   "status not in (0,1,2,7) and taskId=?", (taskId,))


def getJobTaskCountByAll(taskId):
    return sqlBase.fetch_first_val("select count(id) from job_task_item where taskId=?", (taskId,))


def getJobTaskById(taskId):
    rst = sqlBase.fetchall_to_table("select * from job_task where id=?", (taskId,))
    if rst:
        return rst[0]
    else:
        raise Exception("未找到任务，可能已经被删除_/_Task not found, may have been deleted")


def addJobTask(jobTask):
    return sqlBase.execute_insert("insert into job_task (jobId, runTime) "
                                  "VALUES (:jobId, :runTime)", jobTask)


def updateJobTaskStatus(taskId, status, errMsg=None):
    sqlBase.execute_update(f"update job_task set status=?, errMsg=? where id=?", (status, errMsg, taskId))


def updateJobTaskStatusByStatus():
    # 用于重启后，更新所有未完成的任务为中止
    sqlBase.execute_update("update job_task set status=4 where status in (0, 1)")


def updateJobTaskStatusByStatusAndJobId(jobId):
    # 用于任务禁用，更新所有未完成的任务为中止
    sqlBase.execute_update("update job_task set status=4 where status in (0, 1) and jobId=?", (jobId,))


def deleteJobTaskByTaskId(taskId):
    sqlBase.execute_update("delete from job_task_item where taskId=?", (taskId,))
    sqlBase.execute_update("delete from job_task where id=?", (taskId,))


def deleteJobTaskByRunTime(runTime):
    sqlBase.execute_update("delete from job_task_item where taskId in "
                           "(select id from job_task where runTime < ?)", (runTime,))
    sqlBase.execute_update("delete from job_task where runTime < ?", (runTime,))


def addJobTaskItemMany(jobTaskItemList):
    sqlBase.execute_manny(
        "insert into job_task_item (taskId, srcPath, dstPath, fileName, fileSize, type, alistTaskId, status, errMsg) "
        "VALUES (:taskId, :srcPath, :dstPath, :fileName, :fileSize, :type, :alistTaskId, :status, :errMsg)",
        jobTaskItemList)


def getJobTaskItemList(req):
    return sqlBase.fetchall_to_page("select * from job_task_item where taskId=:taskId "
                                    f"{'and status=:status ' if 'status' in req else ''}"
                                    f"{'and type=:type ' if 'type' in req else ''}"
                                    "order by createTime desc ", req)


def getUndoneJobTaskItemList(taskId):
    return sqlBase.fetchall_to_table("select * from job_task_item where taskId=? "
                                     "and status not in (2,4,7)", (taskId,))


def getUnSuccessJobTaskItemList(taskId):
    return sqlBase.fetchall_to_table("select * from job_task_item where taskId=? "
                                     "and status != 2", (taskId,))


def updateJobTaskItemStatusByIdMany(taskList):
    sqlBase.execute_manny("update job_task_item set status=:status, progress=:progress, errMsg=:errMsg "
                          "where id=:id", taskList)


def updateJobTaskItemByAlistTaskId(alistTaskId, status, progress):
    sqlBase.execute_update("update job_task_item set status=?, progress=? "
                           "where alistTaskId=?", (status, progress, alistTaskId))
