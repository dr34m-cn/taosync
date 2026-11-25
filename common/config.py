import configparser
import logging
import math
import os
import tempfile
import threading
from urllib.parse import urlsplit

from common.LNG import get_context_lang
from common.locales import t
from common.commonUtils import generatePasswd, readOrSet

sysConfig = None
DEFAULT_PASSWORD = 'RANDOM'
CONFIG_LOCK = threading.RLock()
EDITABLE_SETTINGS = ('task_save', 'timeout', 'aliyun_auth_server', 'source_full_scan_days', 'anonymous_stats')


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
            'timeout': 72,
            'anonymous_stats': True,
            'source_full_scan_days': 15,
            'aliyun_auth_server': 'https://taoapi.dr34m.cn'
        }
        password = os.getenv('TAO_PASSWORD')
        if password is None:
            password = os.getenv('TAO_PASSWD', DEFAULT_PASSWORD)

        def readValue(key, value):
            if key == 'anonymous_stats':
                try:
                    return configparser.ConfigParser.BOOLEAN_STATES[value.strip().lower()]
                except KeyError:
                    raise ValueError('invalid boolean') from None
            if key == 'source_full_scan_days':
                return float(value)
            if isinstance(sCfg[key], int):
                return int(value)
            return value.strip() or sCfg[key]

        for key in sCfg:
            envKey = 'TAO_TASK_TIMEOUT' if key == 'timeout' else 'TAO_' + key.upper()
            value = os.getenv(envKey)
            try:
                if key == 'source_full_scan_days' and value is None:
                    hours = os.getenv('TAO_SOURCE_FULL_SCAN_HOURS')
                    if hours is not None:
                        sCfg[key] = float(hours) / 24
                elif value is not None:
                    sCfg[key] = readValue(key, value)
            except (TypeError, ValueError):
                logging.getLogger().error(f'环境变量读取失败_/_Invalid environment setting: {envKey}')
        if os.path.exists('data/config.ini'):
            try:
                cfg = configparser.ConfigParser()
                cfg.read('data/config.ini', encoding='utf8')
                tao = cfg['tao']
                if 'password' in tao:
                    password = tao.get('password', raw=True)
                for keyItem in sCfg:
                    option = keyItem
                    if keyItem == 'timeout' and 'task_timeout' in tao:
                        option = 'task_timeout'
                    elif keyItem == 'source_full_scan_days' and keyItem not in tao:
                        option = 'source_full_scan_hours'
                    if option in tao:
                        try:
                            value = readValue(keyItem, tao.get(option, raw=True))
                            sCfg[keyItem] = value / 24 if option == 'source_full_scan_hours' else value
                        except (TypeError, ValueError):
                            logging.getLogger().error(f'配置项读取失败_/_Invalid config setting: {option}')
            except Exception as e:
                logger = logging.getLogger()
                error_type = type(e).__name__
                logger.error(f"配置文件读取失败，将使用环境变量或默认配置_/_config.ini read error: {error_type}")
        if not password or not password.strip():
            password = DEFAULT_PASSWORD
        sysConfig = {
            'db': {
                'dbname': dbname
            },
            'server': {
                'passwdStr': passwdStr,
                'password': password,
                **sCfg
            }
        }
    return sysConfig


def getSettings():
    with CONFIG_LOCK:
        server = getConfig()['server']
        return {key: server[key] for key in EDITABLE_SETTINGS}


def updateSettings(values):
    if not isinstance(values, dict) or not values or set(values) - set(EDITABLE_SETTINGS):
        raise ValueError('Unsupported settings')
    normalized = {}
    for key, value in values.items():
        if key == 'anonymous_stats':
            if type(value) is not bool:
                raise ValueError(t('invalid_stats_setting', get_context_lang()))
        elif key == 'aliyun_auth_server':
            if not isinstance(value, str):
                raise ValueError('aliyun_auth_server must be an HTTP(S) URL')
            value = value.strip().rstrip('/')
            url = urlsplit(value)
            if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError('aliyun_auth_server must be an HTTP(S) URL')
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f'{key} must be a non-negative number')
            if key != 'source_full_scan_days':
                if value != int(value):
                    raise ValueError(f'{key} must be an integer')
                value = int(value)
        normalized[key] = value
    with CONFIG_LOCK:
        server = getConfig()['server']
        parser = configparser.ConfigParser(interpolation=None)
        if os.path.exists('data/config.ini'):
            with open('data/config.ini', encoding='utf-8') as source:
                parser.read_file(source)
        if not parser.has_section('tao'):
            parser.add_section('tao')
        settings = {key: normalized.get(key, server[key]) for key in EDITABLE_SETTINGS}
        for key, value in settings.items():
            parser.set('tao', key, str(value))
        parser.remove_option('tao', 'source_full_scan_hours')
        if parser.has_option('tao', 'task_timeout'):
            parser.set('tao', 'task_timeout', str(settings['timeout']))
        os.makedirs('data', exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='config-', suffix='.ini', dir='data')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                parser.write(output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, 'data/config.ini')
        finally:
            if os.path.exists(temporary):
                os.remove(temporary)
        server.update(settings)
        return settings
