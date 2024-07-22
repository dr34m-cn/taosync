"""
@Author：dr34m
@Date  ：2024/7/8 16:52 
"""
from common import sqlBase


def getAlistList():
    return sqlBase.fetchall_to_table("select * from alist_list")


def getAlistById(alistId):
    rst = sqlBase.fetchall_to_table("select * from alist_list where id=?", (alistId,))
    if rst:
        return rst[0]
    else:
        raise Exception("未找到alist，可能已经被删除")


def addAlist(alist):
    return sqlBase.execute_insert("insert into alist_list (remark, url, userName, token) "
                                  "values (:remark, :url, :userName, :token)", alist)


def updateAlist(alist):
    sqlBase.execute_update(f"update alist_list set remark=:remark, url=:url"
                           f"{', token=:token' if 'token' in alist else ''}"
                           f" where id=:id", alist)


def removeAlist(alistId):
    sqlBase.execute_update("delete from alist_list where id=?", (alistId,))
