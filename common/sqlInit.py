from common import commonUtils
from common import sqlBase
from common.config import DEFAULT_PASSWORD, getConfig


@sqlBase.connect_sql
def init_sql(conn):
    cuVersion = 260718
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE name='user_list'")
    userTableExists = cursor.fetchone() is not None
    if userTableExists:
        cursor.execute("select count(*) from user_list")
        if cursor.fetchone()[0] == 0:
            # A process kill during the very first initialization can leave
            # empty DDL tables behind. Recover that state, but never destroy a
            # database that still contains jobs, engines, mounts, or notices.
            has_business_data = False
            for table in ('job_source_snapshot', 'job_source_snapshot_meta',
                          'storage_mount', 'notify', 'job_task_item', 'job_task', 'job'):
                cursor.execute(
                    "select count(*) from sqlite_master where type='table' and name=?",
                    (table,),
                )
                if cursor.fetchone()[0] and cursor.execute(
                    "select count(*) from " + table
                ).fetchone()[0]:
                    has_business_data = True
                    break
            if not has_business_data:
                cursor.execute(
                    "select count(*) from sqlite_master where type='table' and name='alist_list'"
                )
                if cursor.fetchone()[0]:
                    cursor.execute(
                        "select count(*) from alist_list where url <> 'taosync://internal'"
                    )
                    has_business_data = cursor.fetchone()[0] > 0
            if has_business_data:
                raise RuntimeError(
                    "database has storage data but no administrator user; refusing destructive recovery"
                )
            for table in ('job_source_snapshot', 'job_source_snapshot_meta',
                          'storage_mount', 'notify', 'job_task_item', 'job_task',
                          'job', 'alist_list', 'user_list'):
                cursor.execute("drop table if exists " + table)
            userTableExists = False
    passwd = None
    if not userTableExists:
        configured_password = getConfig()['server']['password']
        passwd = (commonUtils.generatePasswd()
                  if configured_password == DEFAULT_PASSWORD
                  else configured_password)
        cursor.execute("create table user_list("
                       "id integer primary key autoincrement,"
                       "userName text,"                             # 用户名
                       "passwd text,"                               # 密码
                       f"sqlVersion integer DEFAULT {cuVersion},"   # 数据库版本
                       "createTime integer DEFAULT (strftime('%s', 'now'))"
                       ")")
        cursor.execute("insert into user_list(userName, passwd) values ('admin', ?)",
                       (commonUtils.passwd2md5(passwd), ))
        cursor.execute("create table alist_list("
                       "id integer primary key autoincrement,"
                       "remark text,"       # 备注
                       "url text,"          # 地址，例如http://localhost:5244
                       "userName text,"     # 用户名
                       "token text,"        # 令牌
                       "engineType text DEFAULT 'alist',"
                       "systemKey text DEFAULT NULL,"
                       "protected integer DEFAULT 0,"
                       "createTime integer DEFAULT (strftime('%s', 'now')),"
                       " unique (url, userName))")
        cursor.execute("create unique index idx_alist_system_key on alist_list(systemKey) "
                       "where systemKey is not null")
        cursor.execute("insert into alist_list (remark, url, userName, token, engineType, systemKey, protected) "
                       "values (NULL, 'taosync://internal', 'TaoSync', NULL, 'taosync', 'taosync', 1)")
        cursor.execute("create table storage_mount("
                       "id integer primary key autoincrement,"
                       "engineId integer not null,"
                       "name text not null,"
                       "driverType text not null,"
                       "config text not null,"
                       "enabled integer DEFAULT 1,"
                       "configVersion integer DEFAULT 1,"
                       "authVersion integer DEFAULT 1,"
                       "createTime integer DEFAULT (strftime('%s', 'now')),"
                       "unique (engineId, name))")
        cursor.execute("create table job("
                       "id integer primary key autoincrement,"
                       "enable integer DEFAULT 1,"          # 启用，1-启用，0-停用
                       "remark text,"                       # 备注
                       "srcPath text,"                      # 来源目录，结尾有无斜杠都可，建议有斜杠
                       "dstPath text,"                      # 目标目录，结尾有无斜杠都可，建议有斜杠，多个以英文冒号[:]分隔
                       "alistId integer,"                   # 引擎id，alist_list.id
                       "useCacheT integer DEFAULT 0,"       # 扫描目标目录时，是否使用缓存，0-不使用，1-使用
                       "scanIntervalT integer DEFAULT 0,"   # 目标目录扫描间隔，单位秒
                       "useCacheS integer DEFAULT 0,"       # 扫描源目录时，是否使用缓存，0-不使用，1-使用
                       "scanIntervalS integer DEFAULT 0,"   # 源目录扫描间隔，单位秒
                       "method integer,"                    # 同步方式，0-仅新增，1-全同步，2-移动模式
                       "sourceMode integer DEFAULT 0,"
                       "interval integer,"                  # 同步间隔，单位：分钟
                       "isCron integer DEFAULT 0,"          # 是否使用cron，0-使用interval, 1-使用cron，2-仅手动
                       "year text DEFAULT NULL,"            # 四位数的年份
                       "month text DEFAULT NULL,"           # 1-12月
                       "day text DEFAULT NULL,"             # 1-31日
                       "week text DEFAULT NULL,"            # 1-53
                       "day_of_week text DEFAULT NULL,"     # 0-6
                       "hour text DEFAULT NULL,"            # 0-23
                       "minute text DEFAULT NULL,"          # 0-59
                       "second text DEFAULT NULL,"          # 0-59
                       "start_date text DEFAULT NULL,"      # 开始时间
                       "end_date text DEFAULT NULL,"        # 结束时间
                       "exclude text DEFAULT NULL,"         # 排除无需同步项，类似gitignore语法，英文冒号分隔多个规则
                       "minFileSize integer DEFAULT NULL,"  # 过滤小于该字节数的文件，NULL-不限制
                       "maxFileSize integer DEFAULT NULL,"  # 过滤大于该字节数的文件，NULL-不限制
                       "createTime integer DEFAULT (strftime('%s', 'now')),"
                       " unique (srcPath, dstPath, alistId))")
        cursor.execute("create table job_source_snapshot_meta("
                       "jobId integer primary key,"
                       "initialized integer DEFAULT 0,"
                       "scanTime integer DEFAULT NULL,"
                       "entryCount integer DEFAULT 0"
                       ")")
        cursor.execute("create table job_source_snapshot("
                       "jobId integer not null,"
                       "path text not null,"
                       "isDir integer DEFAULT 0,"
                       "size integer DEFAULT NULL,"
                       "fingerprint text DEFAULT NULL,"
                       "primary key (jobId, path)"
                       ")")
        cursor.execute("create table job_task("
                       "id integer primary key autoincrement,"
                       "jobId integer,"             # 所属工作id，job.id
                       "status integer DEFAULT 1,"  # 状态，0-等待中，1-进行中，2-成功，3-完成（部分失败），4-因重启而中止，5-超时，6-失败，7-手动终止
                       "errMsg text,"               # 失败原因
                       "runTime integer,"           # 开始时间，秒级时间戳
                       "taskNum text,"              # 结果数量json字符串
                       "createTime integer DEFAULT (strftime('%s', 'now'))"
                       ")")
        cursor.execute("create table job_task_item("
                       "id integer primary key autoincrement,"
                       "taskId integer,"            # 所属任务id，job_task.id
                       "srcPath text,"              # 来源路径
                       "dstPath text,"              # 目标路径
                       "isPath integer DEFAULT 0,"  # 是否是目录，0-文件，1-目录
                       "fileName text,"             # 文件名
                       "fileSize integer,"          # 文件大小
                       "type integer,"              # 操作类型，0-复制，1-删除，2-移动
                       "alistTaskId text,"          # alist任务id，仅限复制任务，否则为空
                       "status integer DEFAULT 0,"  # 状态，0-等待中，1-运行中，2-成功，3-取消中，4-已取消，5-出错（将重试），6-失败中
                                                    # ，7-已失败，8-等待重试中，9-等待重试回调执行中
                                                    # 对于删除任务，只有0-等待、2-成功、7-失败
                       "progress real,"             # 进度，仅限复制任务，否则为空
                       "errMsg text,"               # 失败原因
                       "createTime integer DEFAULT (strftime('%s', 'now'))"
                       ")")
        cursor.execute("create table notify("
                       "id integer primary key autoincrement,"
                       "enable integer DEFAULT 1,"  # 启用，1-启用，0-停用
                       "method integer,"            # 方式：0-自定义；1-server酱；2-钉钉；待扩展更多
                       "params text,"               # 以json字符串存储参数
                       "createTime integer DEFAULT (strftime('%s', 'now'))"
                       ")")
        conn.commit()
    else:
        try:
            cursor.execute("SELECT sqlVersion FROM user_list limit 1")
            sqlVersion = cursor.fetchone()[0]
        except Exception as e:
            sqlVersion = 0
            if 'sqlVersion' not in str(e):
                import logging
                logger = logging.getLogger()
                logger.exception(e)
        if sqlVersion < cuVersion:
            if sqlVersion < 240731:
                cursor.execute(f"alter table user_list add column sqlVersion integer default {cuVersion}")
                cursor.execute("alter table job_task add column errMsg text")
            if sqlVersion < 240813:
                cursor.execute("alter table job drop column cron")
                cursor.execute("alter table job add column isCron integer DEFAULT 0")
                cursor.execute("alter table job add column year text DEFAULT NULL")
                cursor.execute("alter table job add column month text DEFAULT NULL")
                cursor.execute("alter table job add column day text DEFAULT NULL")
                cursor.execute("alter table job add column week text DEFAULT NULL")
                cursor.execute("alter table job add column day_of_week text DEFAULT NULL")
                cursor.execute("alter table job add column hour text DEFAULT NULL")
                cursor.execute("alter table job add column minute text DEFAULT NULL")
                cursor.execute("alter table job add column second text DEFAULT NULL")
                cursor.execute("alter table job add column start_date text DEFAULT NULL")
                cursor.execute("alter table job add column end_date text DEFAULT NULL")
            if sqlVersion < 240905:
                cursor.execute("alter table job add column exclude text DEFAULT NULL")
            if sqlVersion < 241014:
                cursor.execute("create table notify("
                               "id integer primary key autoincrement,"
                               "enable integer DEFAULT 1,"
                               "method integer,"
                               "params text,"
                               "createTime integer DEFAULT (strftime('%s', 'now'))"
                               ")")
            if sqlVersion < 250307:
                cursor.execute("alter table job_task add column taskNum text")
            if sqlVersion < 250416:
                cursor.execute("alter table job add column remark text")
            if sqlVersion < 250520:
                cursor.execute("alter table job_task_item add column isPath integer DEFAULT 0")
            if sqlVersion < 250608:
                cursor.execute("alter table job rename column speed to useCacheT")
                cursor.execute("alter table job add column scanIntervalT integer DEFAULT 0")
                cursor.execute("alter table job add column useCacheS integer DEFAULT 0")
                cursor.execute("alter table job add column scanIntervalS integer DEFAULT 0")
                cursor.execute("update job set scanIntervalT = 10, useCacheT = 0 where useCacheT = 2")
            if sqlVersion < 260715:
                cursor.execute("alter table job add column minFileSize integer DEFAULT NULL")
                cursor.execute("alter table job add column maxFileSize integer DEFAULT NULL")
            if sqlVersion < 260716:
                cursor.execute("create table if not exists alist_list("
                               "id integer primary key autoincrement, remark text, url text,"
                               "userName text, token text,"
                               "createTime integer DEFAULT (strftime('%s', 'now')),"
                               "unique (url, userName))")
                cursor.execute("pragma table_info(alist_list)")
                engineColumns = {row[1] for row in cursor.fetchall()}
                if 'engineType' not in engineColumns:
                    cursor.execute("alter table alist_list add column engineType text DEFAULT 'alist'")
                if 'systemKey' not in engineColumns:
                    cursor.execute("alter table alist_list add column systemKey text DEFAULT NULL")
                if 'protected' not in engineColumns:
                    cursor.execute("alter table alist_list add column protected integer DEFAULT 0")
                cursor.execute("update alist_list set engineType='alist' where engineType is null")
                cursor.execute("create unique index if not exists idx_alist_system_key "
                               "on alist_list(systemKey) where systemKey is not null")
                cursor.execute("create table if not exists storage_mount("
                               "id integer primary key autoincrement,"
                               "engineId integer not null,"
                               "name text not null,"
                               "driverType text not null,"
                               "config text not null,"
                               "enabled integer DEFAULT 1,"
                               "configVersion integer DEFAULT 1,"
                               "authVersion integer DEFAULT 1,"
                               "createTime integer DEFAULT (strftime('%s', 'now')),"
                               "unique (engineId, name))")
            if sqlVersion < 260717:
                cursor.execute("select count(*) from sqlite_master where type='table' and name='job'")
                if cursor.fetchone()[0]:
                    cursor.execute("pragma table_info(job)")
                    jobColumns = {row[1] for row in cursor.fetchall()}
                    if 'sourceMode' not in jobColumns:
                        cursor.execute("alter table job add column sourceMode integer DEFAULT 0")
                cursor.execute("create table if not exists job_source_snapshot_meta("
                               "jobId integer primary key,"
                               "initialized integer DEFAULT 0,"
                               "scanTime integer DEFAULT NULL,"
                               "entryCount integer DEFAULT 0"
                               ")")
                cursor.execute("create table if not exists job_source_snapshot("
                               "jobId integer not null,"
                               "path text not null,"
                               "isDir integer DEFAULT 0,"
                               "size integer DEFAULT NULL,"
                               "fingerprint text DEFAULT NULL,"
                               "primary key (jobId, path)"
                               ")")
            if sqlVersion < 260718:
                cursor.execute("select count(*) from sqlite_master "
                               "where type='table' and name='job_source_snapshot'")
                if cursor.fetchone()[0]:
                    cursor.execute("pragma table_info(job_source_snapshot)")
                    snapshotColumns = {row[1] for row in cursor.fetchall()}
                    if 'fingerprint' not in snapshotColumns:
                        cursor.execute("alter table job_source_snapshot "
                                       "add column fingerprint text DEFAULT NULL")
            cursor.execute(f"update user_list set sqlVersion={cuVersion}")
            conn.commit()
    # Keep the built-in engine present even when a migration was interrupted.
    cursor.execute("create table if not exists alist_list("
                   "id integer primary key autoincrement, remark text, url text,"
                   "userName text, token text,"
                   "createTime integer DEFAULT (strftime('%s', 'now')),"
                   "unique (url, userName))")
    cursor.execute("pragma table_info(alist_list)")
    engineColumns = {row[1] for row in cursor.fetchall()}
    if 'engineType' not in engineColumns:
        cursor.execute("alter table alist_list add column engineType text DEFAULT 'alist'")
    if 'systemKey' not in engineColumns:
        cursor.execute("alter table alist_list add column systemKey text DEFAULT NULL")
    if 'protected' not in engineColumns:
        cursor.execute("alter table alist_list add column protected integer DEFAULT 0")
    cursor.execute("create table if not exists storage_mount("
                   "id integer primary key autoincrement, engineId integer not null,"
                   "name text not null, driverType text not null, config text not null,"
                   "enabled integer DEFAULT 1, configVersion integer DEFAULT 1, authVersion integer DEFAULT 1,"
                   "createTime integer DEFAULT (strftime('%s', 'now')),"
                   "unique (engineId, name))")
    cursor.execute("pragma table_info(storage_mount)")
    mountColumns = {row[1] for row in cursor.fetchall()}
    if 'configVersion' not in mountColumns:
        cursor.execute("alter table storage_mount add column configVersion integer DEFAULT 1")
    if 'authVersion' not in mountColumns:
        cursor.execute("alter table storage_mount add column authVersion integer DEFAULT 1")
    cursor.execute("select count(*) from sqlite_master where type='table' and name='job'")
    if cursor.fetchone()[0]:
        cursor.execute("pragma table_info(job)")
        jobColumns = {row[1] for row in cursor.fetchall()}
        if 'sourceMode' not in jobColumns:
            cursor.execute("alter table job add column sourceMode integer DEFAULT 0")
    cursor.execute("create table if not exists job_source_snapshot_meta("
                   "jobId integer primary key, initialized integer DEFAULT 0,"
                   "scanTime integer DEFAULT NULL, entryCount integer DEFAULT 0"
                   ")")
    cursor.execute("create table if not exists job_source_snapshot("
                   "jobId integer not null, path text not null,"
                   "isDir integer DEFAULT 0, size integer DEFAULT NULL,"
                   "fingerprint text DEFAULT NULL,"
                   "primary key (jobId, path)"
                   ")")
    cursor.execute("pragma table_info(job_source_snapshot)")
    snapshotColumns = {row[1] for row in cursor.fetchall()}
    if 'fingerprint' not in snapshotColumns:
        cursor.execute("alter table job_source_snapshot "
                       "add column fingerprint text DEFAULT NULL")
    cursor.execute("create unique index if not exists idx_alist_system_key "
                   "on alist_list(systemKey) where systemKey is not null")
    cursor.execute("update alist_list set engineType='alist' where engineType is null")
    cursor.execute("select id from alist_list where systemKey='taosync' limit 1")
    if cursor.fetchone() is None:
        cursor.execute("insert into alist_list (remark, url, userName, token, engineType, systemKey, protected) "
                       "values (NULL, 'taosync://internal', 'TaoSync', NULL, 'taosync', 'taosync', 1)")
    else:
        cursor.execute("update alist_list set userName='TaoSync', url='taosync://internal', "
                       "engineType='taosync', protected=1 where systemKey='taosync'")
    conn.commit()
    cursor.close()
    return passwd
