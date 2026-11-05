import hmac
import threading
import time

from common import commonUtils, config
from common.LNG import G
from mapper import userMapper

"""
密码错误记录：按客户端（登录时为来源 IP，改密时为用户）分别记录错误时间戳，
避免任意访问者输错密码导致管理员本人也被锁定
"""
ERR_PWD = {}
ERR_PWD_LOCK = threading.Lock()
ERR_PWD_WINDOW = 300
ERR_PWD_MAX = 3


def _errKey(clientKey):
    return str(clientKey) if clientKey else '__global__'


def checkPwdTime(clientKey=None):
    timeNow = int(time.time())
    key = _errKey(clientKey)
    with ERR_PWD_LOCK:
        for itemKey in list(ERR_PWD.keys()):
            ERR_PWD[itemKey] = [item for item in ERR_PWD[itemKey] if item + ERR_PWD_WINDOW >= timeNow]
            if not ERR_PWD[itemKey]:
                del ERR_PWD[itemKey]
        if len(ERR_PWD.get(key, [])) > ERR_PWD_MAX:
            raise Exception(G('passwd_wrong_max_time'))


def addPwdError(clientKey=None):
    with ERR_PWD_LOCK:
        ERR_PWD.setdefault(_errKey(clientKey), []).append(int(time.time()))


def getUser(userId, userName=None):
    """
    通过用户名获取用户信息
    :param userId: 用户id
    :param userName: 用户名
    :return: 用户信息
    """
    return userMapper.getUserByName(userName) if not userId else userMapper.getUserById(userId)


def checkPwd(userId, passwd, userName=None, clientKey=None):
    """
    检查密码是否正确；旧版 MD5 摘要在校验成功后自动升级为 PBKDF2
    :param userId: 用户id
    :param passwd: 密码
    :param userName: 用户名
    :param clientKey: 错误次数限制的维度（例如来源 IP）
    :return: 用户信息
    """
    checkPwdTime(clientKey)
    try:
        user = getUser(userId, userName)
        if not commonUtils.verifyPasswd(passwd, user['passwd']):
            raise Exception(G('passwd_wrong'))
    except Exception as e:
        addPwdError(clientKey)
        raise e
    if commonUtils.passwdNeedsRehash(user['passwd']):
        newHash = commonUtils.hashPasswd(passwd)
        userMapper.resetPasswd(user['id'], newHash)
        user = dict(user)
        user['passwd'] = newHash
    return user


def editPasswd(userId, passwd, oldPasswd):
    """
    修改密码
    :param userId: 用户id
    :param passwd: 新密码
    :param oldPasswd: 旧密码
    """
    checkPwd(userId, oldPasswd, clientKey=f'user:{userId}')
    userMapper.resetPasswd(userId, commonUtils.hashPasswd(passwd))


def resetPasswd(userName, key, passwd=None):
    """
    重置密码
    :param userName: 用户名
    :param key: 加密字符串
    :param passwd: 新密码
    :return:
    """
    cfg = config.getConfig()
    user = userMapper.getUserByName(userName.strip())
    if not hmac.compare_digest(key.strip().encode('utf-8'), cfg['server']['passwdStr'].encode('utf-8')):
        raise Exception(G('key_wrong'))
    if passwd is None:
        passwd = commonUtils.generatePasswd(8)
        userMapper.resetPasswd(user['id'], commonUtils.hashPasswd(passwd))
        return passwd
    userMapper.resetPasswd(user['id'], commonUtils.hashPasswd(passwd.strip()))
