import configparser
import logging
import os

from common.commonUtils import generatePasswd, readOrSet

sysConfig = None
DEFAULT_PASSWORD = 'RANDOM'


def getPasswordStr():
    """
    获取加密字符串
    :return: 加密字符串
    """
    fileName = 'data/secret.key'
    passwdStr = readOrSet(fileName, generatePasswd(256))
    return passwdStr


def getConfig():
    global sysConfig
    if sysConfig is None:
        passwdStr = getPasswordStr()
        dbname = 'data/taoSync.db'
        sCfg = {
            'port': 8023,
            'expires': 2,
            'log_level': 1,
            'console_level': 2,
            'log_save': 7,
            'task_save': 0,
            'timeout': 72
        }
        textCfg = {
            'aliyun_auth_server': ''
        }
        password = DEFAULT_PASSWORD
        if os.path.exists('data/config.ini'):
            try:
                cfg = configparser.ConfigParser()
                cfg.read('data/config.ini', encoding='utf8')
                tao = cfg['tao']
                if 'password' in tao:
                    password = tao.get('password', raw=True)
                for keyItem in sCfg.keys():
                    if keyItem in tao:
                        sCfg[keyItem] = int(tao[keyItem])
                for keyItem in textCfg.keys():
                    if keyItem in tao:
                        textCfg[keyItem] = tao.get(keyItem, raw=True).strip()
            except Exception as e:
                logger = logging.getLogger()
                error_type = type(e).__name__
                logger.error(f"配置文件读取失败，将使用默认配置_/_config.ini read error: {error_type}")
        else:
            password = os.getenv('TAO_PASSWORD')
            if password is None:
                password = os.getenv('TAO_PASSWD', DEFAULT_PASSWORD)
            try:
                sCfg['port'] = int(os.getenv('TAO_PORT', 8023))
                sCfg['expires'] = int(os.getenv('TAO_EXPIRES', 2))
                sCfg['log_level'] = int(os.getenv('TAO_LOG_LEVEL', 1))
                sCfg['console_level'] = int(os.getenv('TAO_CONSOLE_LEVEL', 2))
                sCfg['log_save'] = int(os.getenv('TAO_LOG_SAVE', 7))
                sCfg['task_save'] = int(os.getenv('TAO_TASK_SAVE', 0))
                sCfg['timeout'] = int(os.getenv('TAO_TASK_TIMEOUT', 72))
                textCfg['aliyun_auth_server'] = os.getenv('TAO_ALIYUN_AUTH_SERVER', '').strip()
            except Exception as e:
                logger = logging.getLogger()
                logger.error(f"环境变量读取失败，将使用默认配置_/_ENV read error: {e}")
                logger.exception(e)
        env_aliyun_auth_server = os.getenv('TAO_ALIYUN_AUTH_SERVER')
        # 环境变量为空时不覆盖，Docker 镜像预置的空值不应使 config.ini 配置失效
        if env_aliyun_auth_server is not None and env_aliyun_auth_server.strip():
            textCfg['aliyun_auth_server'] = env_aliyun_auth_server.strip()
        if not password or not password.strip():
            password = DEFAULT_PASSWORD
        sysConfig = {
            'db': {
                'dbname': dbname
            },
            'server': {
                'passwdStr': passwdStr,
                'password': password,
                **sCfg,
                **textCfg
            }
        }
    return sysConfig
