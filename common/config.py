import os

sysConfig = None


def getPasswordStr():
    if not os.path.exists('data'):
        os.mkdir('data')
    fileName = 'data/secret.key'
    if os.path.exists(fileName):
        with open(fileName, 'r') as file:
            passwdStr = file.read()
    else:
        from common.commonUtils import generatePasswd
        passwdStr = generatePasswd(256)
        with open(fileName, 'w') as file:
            file.write(passwdStr)
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
