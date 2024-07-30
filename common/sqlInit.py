from common import commonUtils
from common import sqlBase


@sqlBase.connect_sql
def init_sql(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE name='user_list'")
    passwd = None
    if cursor.fetchone() is None:
        passwd = commonUtils.generatePasswd()
        cursor.execute("create table user_list("
                       "id integer primary key autoincrement,"
                       "userName text,"     # 用户名
                       "passwd text,"       # 密码
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
                       "enable integer DEFAULT 1,"  # 启用，1-启用，0-停用
                       "srcPath text,"              # 来源目录，结尾有无斜杠都可，建议有斜杠
                       "dstPath text,"              # 目标目录，结尾有无斜杠都可，建议有斜杠
                       "alistId integer,"           # 引擎id，alist_list.id
                       "speed integer,"             # 同步速度：0-标准，1-快速
                       "method integer,"            # 同步方式，0-仅新增，1-全同步
                       "interval integer,"          # 同步间隔，单位：分钟
                       "cron text,"                 # 同步cron（预留，暂时未使用）
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
    cursor.close()
    return passwd
