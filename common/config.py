import os

from common.commonUtils import generatePasswd, readOrSet

sysConfig = None


def getPasswordStr():
    """
    获取加密字符串
    :return: 加密字符串
    """
    if not os.path.exists('data'):
        os.mkdir('data')
    fileName = 'data/secret.key'
    passwdStr = readOrSet(fileName, generatePasswd(256))
    return passwdStr


def getConfig():
    global sysConfig
    if sysConfig is None:
        sysConfig = {
            'db': {
                'dbname': 'data/taoSync.db'
            },
            'server': {
                'port': 8023,
                'passwdStr': getPasswordStr(),
                'cookieExpiresDays': int(os.getenv('TAO_EXPIRES', 2)),
                'logLevel': int(os.getenv('TAO_LOG_LEVEL', 1)),
                'logSave': int(os.getenv('TAO_LOG_SAVE', 7)),
                'taskSave': int(os.getenv('TAO_TASK_SAVE', 0)),
                'timeout': int(os.getenv('TAO_TASK_TIMEOUT', 72))
            }
        }
    return sysConfig
