from common import sqlBase


def getNotifyList(needEnable=False):
    """
    获取通知配置列表
    :param needEnable:
    :return:
    """
    sqlBase.fetchall_to_table(f"select * from notify{' where enable = 1' if needEnable else ''}")


def addNotify(notify):
    """
    新增通知配置
    :param notify:
    :return:
    """
    sqlBase.execute_insert("insert into notify(enable, method, params) values (:enable, :method, :params)", notify)


def editNotify(notify):
    """
    编辑通知配置
    :param notify:
    :return:
    """
    sqlBase.execute_update("update notify set enable=:enable, method=:method, params=:params where id = :id", notify)


def updateNotifyStatus(notifyId, enable):
    """
    更新通知配置状态
    :param notifyId:
    :param enable:
    :return:
    """
    sqlBase.execute_update("update notify set enable=? where id=?", (enable, notifyId))
