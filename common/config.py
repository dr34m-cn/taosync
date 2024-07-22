import os

passwdStr = None


def getPasswordStr():
    global passwdStr
    if passwdStr is None:
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


CONFIG = {
    'db': {
        'dbname': 'data/taoSync.db'
    },
    'server': {
        'port': 8023,
        'passwdStr': getPasswordStr(),
        'cookieExpiresDays': os.getenv('TAO_EXPIRES', 2),
        'logLevel': os.getenv('TAO_LOG_LEVEL', 1),
        'logSave': os.getenv('TAO_LOG_SAVE', 7),
        'taskSave': os.getenv('TAO_TASK_SAVE', 0),
        'timeout': os.getenv('TAO_TASK_TIMEOUT', 72)
    }
}
