"""
@Author：dr34m
@Date  ：2024/8/16 13:52 
"""
from common.commonUtils import readOrSet

sysLanguage = None
allLng = {
    'zh_cn': {
        'success': '操作成功',
        'lost_part': '入参不全',
        'same_exists': '已存在相同数据，请检查！',
        'sign_in': '请登录',
        'login_expired': '登录失效',
        'alist_not_found': '未找到alist，可能已经被删除',
        'job_not_found': '未找到作业，可能已经被删除',
        'task_not_found': '未找到任务，可能已经被删除',
        'user_not_found': '用户不存在',
        'alist_connect_fail': 'alist连接失败，请检查是否填写正确',
        'address_incorrect': 'alist地址格式有误',
        'code_not_200': '状态码非200',
        'alist_un_auth': 'AList鉴权失败，可能是令牌已失效',
        'alist_fail_code_reason': 'AList返回{}错误，原因为：{}',
        'without_token': '地址改变时令牌必填',
        'add_alist_client_fail': '新增alist客户端时失败，原因为：{}',
        'task_may_delete': '任务未找到。可能是您手动到AList中删除了复制任务；或者Alist因手动/异常奔溃被重启，导致任务记录丢失',
        'do_job_err': '执行任务失败，原因为：{}',
        'job_running': '当前有任务执行中，请稍后再试',
        'interval_lost': '创建间隔型作业时，间隔必填',
        'cron_lost': '创建cron型任务时，至少有一项不为空',
        'cannot_resume_lost_job': '作业不存在无法恢复，请删除后重新创建',
        'stop_fail': '停止定时任务失败，原因为：{}',
        'disable_fail': '禁用定时任务失败，原因为：{}',
        'cancel_fail': '取消任务过程中失败，原因为：{}',
        'disable_then_edit': '请先禁用任务才能编辑',
        'log_del_success': '日志文件{}已被成功删除',
        'log_del_fail': '日志文件{}删除失败，原因为：{}',
        'log_rename_start': '日志定时更名任务启动成功',
        'keep_all_log': '日志保留时间为0，将保留所有日志',
        'keep_all_task': '任务保留时间为0，将保留所有任务',
        'clear_task_start': '定时清理任务启动成功',
        'passwd_wrong': '密码错误',
        'passwd_wrong_max_time': '5分钟内密码错误超过3次，请稍后再试'
    },
    'eng': {
        'success': 'success',
        'lost_part': 'Incomplete participation',
        'same_exists': 'The same data already exists, please check!',
        'sign_in': 'Please sign in',
        'login_expired': 'Login expired',
        'alist_not_found': 'Alist not found, may have been deleted',
        'job_not_found': 'The job was not found and may have been deleted',
        'task_not_found': 'Task not found, may have been deleted',
        'user_not_found': 'User does not exist',
        'alist_connect_fail': 'Alist connection failed, please check whether it is filled in correctly',
        'address_incorrect': 'The alist address format is incorrect',
        'code_not_200': 'Code not 200',
        'alist_un_auth': 'AList authentication failed, possibly because the token has expired',
        'alist_fail_code_reason': 'AList returns {}, reason: {}',
        'without_token': 'Token is required when address changes',
        'add_alist_client_fail': 'Failed to add alist client, reason: {}',
        'task_may_delete': 'task not found. You may have manually deleted the replication task in AList; or Alist was restarted manually or abnormally, resulting in the loss of task records',
        'do_job_err': 'Task execution failed due to: {}',
        'job_running': 'There is a task currently being executed, please try again later',
        'interval_lost': 'When creating an interval job, the interval is required',
        'cron_lost': 'When creating a cron job, at least one of the following items must be non-empty',
        'cannot_resume_lost_job': 'The job does not exist and cannot be restored. Please delete it and create it again',
        'stop_fail': 'Failed to stop the scheduled task due to: {}',
        'disable_fail': 'Failed to pause the scheduled task due to: {}',
        'cancel_fail': 'The task cancellation process failed due to: {}',
        'disable_then_edit': 'Please disable the task before editing it',
        'log_del_success': 'The log file {} has been successfully deleted',
        'log_del_fail': 'Failed to delete log file {}, reason: {}',
        'log_rename_start': 'The log scheduled renaming task was started successfully',
        'keep_all_log': 'The log retention time is 0, all logs will be retained',
        'keep_all_task': 'The task retention time is 0, all tasks will be retained',
        'clear_task_start': 'The scheduled cleanup task was started successfully',
        'passwd_wrong': 'Wrong password',
        'passwd_wrong_max_time': 'The password was incorrect more than 3 times within 5 minutes. Please try again later'
    }
}


def language(lang=None):
    """
    获取或修改语言
    :param lang: 语言，不填为读取，否则是修改
    :return: 读取时为值，否则空
    """
    global sysLanguage
    fileName = 'data/language.txt'
    if lang is None:
        if sysLanguage is None:
            sysLanguage = readOrSet(fileName, 'zh_cn')
        return sysLanguage
    else:
        if lang not in allLng:
            raise Exception(f"no {lang}")
        sysLanguage = lang
        readOrSet(fileName, lang, True)


def G(params):
    """
    根据语言获取文字
    :param params: 文字关键字
    :return:
    """
    cu = allLng[language()]
    return cu[params]
