import time

from common import commonUtils
from common.LNG import G
from mapper import userMapper

"""
密码错误记录，记录错误时间戳
"""
ERR_PWD = []


def checkPwdTime():
    global ERR_PWD
    timeNow = int(time.time())
    for item in ERR_PWD[:]:
        if item + 300 < timeNow:
            ERR_PWD.remove(item)
    if len(ERR_PWD) > 3:
        raise Exception(G('passwd_wrong_max_time'))


def addPwdError():
    global ERR_PWD
    ERR_PWD.append(int(time.time()))


def getUser(userId, userName=None):
    """
    通过用户名获取用户信息
    :param userId: 用户id
    :param userName: 用户名
    :return: 用户信息
    """
    return userMapper.getUserByName(userName) if not userId else userMapper.getUserById(userId)


def checkPwd(userId, passwd, userName=None):
    """
    检查密码是否正确
    :param userId: 用户id
    :param passwd: 密码
    :param userName: 用户名
    :return: 用户信息
    """
    checkPwdTime()
    try:
        user = getUser(userId, userName)
        if commonUtils.passwd2md5(passwd) == user['passwd']:
            return user
        else:
            raise Exception(G('passwd_wrong'))
    except Exception as e:
        addPwdError()
        raise e


def resetPasswd(userId, passwd, oldPasswd):
    """
    重置密码
    :param userId: 用户id
    :param passwd: 新密码
    :param oldPasswd: 旧密码
    """
    checkPwd(userId, oldPasswd)
    userMapper.resetPasswd(userId, commonUtils.passwd2md5(passwd))
