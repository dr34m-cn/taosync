"""
@Author：dr34m
@Date  ：2024/7/9 17:18 
"""
import time

from common import sqlBase
from common.LNG import G

SOURCE_SNAPSHOT_FIELDS = (
    'alistId', 'srcPath', 'dstPath', 'method', 'exclude', 'minFileSize', 'maxFileSize'
)


def sourceSnapshotIdentity(job):
    identity = {key: job.get(key) for key in SOURCE_SNAPSHOT_FIELDS}
    for key in ('alistId', 'method', 'minFileSize', 'maxFileSize'):
        value = identity[key]
        if value is not None:
            try:
                identity[key] = int(value)
            except (TypeError, ValueError):
                pass
    return identity


def getJobList(params=None):
    # 作业列表
    return sqlBase.fetchall_to_page("select * from job order by createTime desc ", params)


def getEnableJobList():
    """
    获取未禁用的作业列表
    :return:
    """
    return sqlBase.fetchall_to_table("select * from job where enable=1")


def getJobById(jobId):
    # 作业详情
    rst = sqlBase.fetchall_to_table("select * from job where id=?", (jobId,))
    if rst:
        return rst[0]
    else:
        raise Exception(G('job_not_found'))


def getJobByTaskId(taskId):
    """
    通过任务id获取作业详情
    :param taskId: 任务id
    :return:
    """
    rst = sqlBase.fetchall_to_table("select * from job where id in (select jobId from job_task where id = ?)",
                                    (taskId,))
    if rst:
        return rst[0]
    else:
        raise Exception(G('job_not_found'))


def addJob(job):
    # 新增作业
    return sqlBase.execute_insert("insert into job (enable, remark, srcPath, dstPath, alistId, useCacheT, "
                                  "scanIntervalT, useCacheS, scanIntervalS, method, sourceMode, interval"
                                  ",isCron, year, month, day, week, day_of_week, hour, minute, second, "
                                  "start_date, end_date, exclude, minFileSize, maxFileSize) "
                                  "VALUES (:enable, :remark, :srcPath, :dstPath, :alistId, :useCacheT, "
                                  ":scanIntervalT, :useCacheS, :scanIntervalS, :method, :sourceMode, :interval, "
                                  ":isCron, :year, :month, :day, :week, :day_of_week, :hour, :minute, :second, "
                                  ":start_date, :end_date, :exclude, :minFileSize, :maxFileSize)", job)


@sqlBase.connect_sql
def updateJob(conn, job, clearSourceSnapshot=False):
    # 更新作业
    try:
        conn.execute("begin immediate")
        cursor = conn.execute(
            "update job set enable=:enable, remark=:remark, srcPath=:srcPath, dstPath=:dstPath, alistId=:alistId, "
            " useCacheT=:useCacheT, scanIntervalT=:scanIntervalT, useCacheS=:useCacheS, scanIntervalS=:scanIntervalS, "
            "method=:method, sourceMode=:sourceMode, interval=:interval, isCron=:isCron, year=:year, "
            "month=:month, day=:day, week=:week, day_of_week=:day_of_week, hour=:hour, minute=:minute, "
            "second=:second, start_date=:start_date, end_date=:end_date, exclude=:exclude, "
            "minFileSize=:minFileSize, maxFileSize=:maxFileSize where id=:id",
            job,
        )
        if cursor.rowcount != 1:
            raise Exception(G('job_not_found'))
        if clearSourceSnapshot:
            conn.execute("delete from job_source_snapshot where jobId=?", (job['id'],))
            conn.execute("delete from job_source_snapshot_meta where jobId=?", (job['id'],))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def updateJobEnable(jobId, enable):
    # 更新作业执行状态
    sqlBase.execute_update("update job set enable = ? where id = ?", (enable, jobId))


@sqlBase.connect_sql
def deleteJob(conn, jobId):
    # 删除作业
    try:
        conn.execute("begin immediate")
        conn.execute("delete from job_source_snapshot where jobId=?", (jobId,))
        conn.execute("delete from job_source_snapshot_meta where jobId=?", (jobId,))
        conn.execute("delete from job_task_item where "
                     "taskId in (select id from job_task where jobId=?)", (jobId,))
        conn.execute("delete from job_task where jobId=?", (jobId,))
        conn.execute("delete from job where id=?", (jobId,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


@sqlBase.connect_sql
def getSourceSnapshot(conn, jobId):
    conn.execute("begin")
    metaRow = conn.execute(
        "select jobId, initialized, scanTime, entryCount "
        "from job_source_snapshot_meta where jobId=?", (jobId,)).fetchone()
    meta = dict(zip(('jobId', 'initialized', 'scanTime', 'entryCount'), metaRow)) if metaRow else {
        'jobId': int(jobId),
        'initialized': 0,
        'scanTime': None,
        'entryCount': 0,
    }
    entryRows = conn.execute(
        "select path, isDir, size, fingerprint from job_source_snapshot "
        "where jobId=? order by path", (jobId,)).fetchall()
    entries = []
    for path, isDir, size, fingerprint in entryRows:
        entry = {'path': path, 'isDir': isDir, 'size': size}
        if fingerprint is not None:
            entry['fingerprint'] = fingerprint
        entries.append(entry)
    conn.commit()
    return {'meta': meta, 'entries': entries}


@sqlBase.connect_sql
def replaceSourceSnapshot(conn, jobId, entries, expectedIdentity=None):
    rowsByPath = {}
    for entry in entries:
        path = entry['path']
        if not isinstance(path, str):
            raise ValueError('snapshot path must be a string')
        isDir = 1 if entry.get('isDir', entry.get('is_dir', 0)) else 0
        fingerprint = entry.get('fingerprint')
        if fingerprint is not None:
            fingerprint = str(fingerprint)
        rowsByPath[path] = (
            int(jobId),
            path,
            isDir,
            None if isDir else entry.get('size'),
            fingerprint,
        )
    rows = list(rowsByPath.values())
    scanTime = int(time.time())
    try:
        conn.execute("begin immediate")
        identityColumns = ', '.join(SOURCE_SNAPSHOT_FIELDS)
        jobRow = conn.execute(
            "select {} from job where id=?".format(identityColumns), (jobId,)
        ).fetchone()
        if jobRow is None:
            raise Exception(G('job_not_found'))
        if expectedIdentity is not None:
            currentIdentity = sourceSnapshotIdentity(
                dict(zip(SOURCE_SNAPSHOT_FIELDS, jobRow))
            )
            if currentIdentity != expectedIdentity:
                raise RuntimeError(G('job_changed_during_sync'))
        conn.execute("delete from job_source_snapshot where jobId=?", (jobId,))
        if rows:
            conn.executemany(
                "insert into job_source_snapshot(jobId, path, isDir, size, fingerprint) "
                "values (?, ?, ?, ?, ?)", rows)
        conn.execute(
            "insert into job_source_snapshot_meta(jobId, initialized, scanTime, entryCount) "
            "values (?, 1, ?, ?) "
            "on conflict(jobId) do update set initialized=1, "
            "scanTime=excluded.scanTime, entryCount=excluded.entryCount",
            (jobId, scanTime, len(rows)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        'jobId': int(jobId),
        'initialized': 1,
        'scanTime': scanTime,
        'entryCount': len(rows),
    }


@sqlBase.connect_sql
def clearSourceSnapshot(conn, jobId):
    try:
        conn.execute("begin immediate")
        conn.execute("delete from job_source_snapshot where jobId=?", (jobId,))
        conn.execute("delete from job_source_snapshot_meta where jobId=?", (jobId,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise


@sqlBase.connect_sql
def clearSourceSnapshotsByEngine(conn, engineId):
    try:
        conn.execute("begin immediate")
        conn.execute(
            "delete from job_source_snapshot where jobId in "
            "(select id from job where alistId=?)", (engineId,)
        )
        conn.execute(
            "delete from job_source_snapshot_meta where jobId in "
            "(select id from job where alistId=?)", (engineId,)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def updateJobTaskNumMany(taskNums):
    """
    批量更新任务的结果数量
    :param taskNums: [{
        'taskId': 1,
        'taskNum': ""
    }]
    :return:
    """
    sqlBase.execute_manny("update job_task set taskNum=:taskNum where id=:taskId", taskNums)


def getJobTaskList(req):
    # 获取任务列表
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
        raise Exception(G('task_not_found'))


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
        "insert into job_task_item (taskId, srcPath, dstPath, isPath, fileName, fileSize, type, alistTaskId, status, errMsg) "
        "VALUES (:taskId, :srcPath, :dstPath, :isPath, :fileName, :fileSize, :type, :alistTaskId, :status, :errMsg)",
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
