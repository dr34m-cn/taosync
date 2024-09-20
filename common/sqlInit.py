from common import commonUtils
from common import sqlBase


@sqlBase.connect_sql
def init_sql(conn):
    cuVersion = 240905
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE name='user_list'")
    passwd = None
    if cursor.fetchone() is None:
        passwd = commonUtils.generatePasswd()
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
                       "createTime integer DEFAULT (strftime('%s', 'now')),"
                       " unique (url, userName))")
        cursor.execute("create table job("
                       "id integer primary key autoincrement,"
                       "enable integer DEFAULT 1,"          # 启用，1-启用，0-停用
                       "srcPath text,"                      # 来源目录，结尾有无斜杠都可，建议有斜杠
                       "dstPath text,"                      # 目标目录，结尾有无斜杠都可，建议有斜杠
                       "alistId integer,"                   # 引擎id，alist_list.id
                       "speed integer,"                     # 同步速度：0-标准，1-快速，2-低速
                       "method integer,"                    # 同步方式，0-仅新增，1-全同步
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
                       "exclude text DEFAULT NULL,"         # 排除无需同步项，以类型-值，英文冒号分隔，示例：0-path/:1-.
                                                            # 类型：0-全匹配，1-开头，2-任意包含，3-结尾
                       "createTime integer DEFAULT (strftime('%s', 'now')),"
                       " unique (srcPath, dstPath, alistId))")
        cursor.execute("create table job_task("
                       "id integer primary key autoincrement,"
                       "jobId integer,"             # 所属工作id，job.id
                       "status integer DEFAULT 1,"  # 状态，0-等待中，1-进行中，2-成功，3-完成（部分失败），4-因重启而中止，5-超时，6-失败
                       "errMsg text,"               # 失败原因
                       "runTime integer,"           # 开始时间，秒级时间戳
                       "createTime integer DEFAULT (strftime('%s', 'now'))"
                       ")")
        cursor.execute("create table job_task_item("
                       "id integer primary key autoincrement,"
                       "taskId integer,"            # 所属任务id，job_task.id
                       "srcPath text,"              # 来源路径
                       "dstPath text,"              # 目标路径
                       "fileName text,"             # 文件名
                       "fileSize integer,"          # 文件大小
                       "type integer,"              # 操作类型，0-复制，1-删除
                       "alistTaskId text,"          # alist任务id，仅限复制任务，否则为空
                       "status integer DEFAULT 0,"  # 状态，0-等待中，1-运行中，2-成功，3-取消中，4-已取消，5-出错（将重试），6-失败中
                                                    # ，7-已失败，8-等待重试中，9-等待重试回调执行中
                                                    # 对于删除任务，只有0-等待、2-成功、7-失败
                       "progress real,"             # 进度，仅限复制任务，否则为空
                       "errMsg text,"               # 失败原因
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
                cursor.execute(f"update user_list set sqlVersion={cuVersion}")
                cursor.execute("alter table job add column exclude text DEFAULT NULL")
            conn.commit()
    cursor.close()
    return passwd
