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


def convertSeconds(seconds):
    hours = int(seconds // 3600)
    remaining_seconds = seconds % 3600
    minutes = int(remaining_seconds // 60)
    seconds = int(remaining_seconds % 60)
    return hours, minutes, seconds

def convertBytes(val):
    """
    把字节转为易读
    :param val:
    :return:
    """
    unitList = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    while i < len(unitList):
        i = i + 1
        if val < 1024 ** (i + 1):
            return f"{val / (1024 ** i):.2f} {unitList[i]}"
    # 如果超出最大单位，显示为最大单位
    return f"{val / (1024 ** (i - 1)):.2f} {unitList[i - 1]}"


def passwd2md5(passwd):
    """
    密码加密（不可解密）
    :param passwd: 密码字符串
    :return: md5字符串
    """
    from common.config import getConfig
    cfg = getConfig()
    passwd_str = cfg['server']['passwdStr']
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
