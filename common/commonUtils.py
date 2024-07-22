import hashlib
import random
import string
from datetime import datetime


def generatePasswd(length=8):
    """
    生成随机密码
    :param length: 密码长度
    :return:
    """
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length))


def passwd2md5(passwd):
    """
    密码加密（不可解密）
    :param passwd: 密码字符串
    :return: md5字符串
    """
    from common.config import CONFIG
    passwd_str = CONFIG['server']['passwdStr']
    hl = hashlib.md5()
    hl.update((passwd + passwd_str).encode(encoding='utf-8'))
    return hl.hexdigest()


def stampToTime(stamp):
    """
    时间戳格式化为时间
    :param stamp: 时间戳，秒级
    :return: 格式化后的时间字符串，如2024-01-01 12:00:35
    """
    return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M:%S")


def timeToStamp(timeStr):
    """
    时间字符串转为时间戳
    :param timeStr: 时间字符串，如2024-01-01 12:00:35
    :return: 时间戳，秒级
    """
    return int(datetime.timestamp(datetime.strptime(timeStr, "%Y-%m-%d %H:%M:%S")))
