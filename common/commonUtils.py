import hashlib
import os
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
    from common.config import getConfig
    CONFIG = getConfig()
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


def readOrSet(fileName, default, force=False):
    """
    从文件读取内容读取，不存在则创建
    :param fileName: 文件名，如data/111.txt
    :param default: 不存在文件时默认值，或强制覆盖值
    :param force: 强制用默认值覆盖
    :return: 结果
    """
    if os.path.exists(fileName) and force is False:
        with open(fileName, 'r') as file:
            fnData = file.read()
    else:
        fnData = default
        with open(fileName, 'w') as file:
            file.write(default)
    return fnData
