import hashlib
import hmac
import os
import secrets
import string
from datetime import datetime

PASSWD_SCHEME = 'pbkdf2_sha256'
PASSWD_ITERATIONS = 120000


def generatePasswd(length=8):
    """
    生成随机密码（密码学安全随机数）
    :param length: 密码长度
    :return:
    """
    characters = string.ascii_letters + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))


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
    旧版密码摘要（MD5 + 系统密钥），仅用于校验升级前保存的密码
    :param passwd: 密码字符串
    :return: md5字符串
    """
    from common.config import getConfig
    cfg = getConfig()
    passwd_str = cfg['server']['passwdStr']
    hl = hashlib.md5()
    hl.update((passwd + passwd_str).encode(encoding='utf-8'))
    return hl.hexdigest()


def hashPasswd(passwd, iterations=PASSWD_ITERATIONS):
    """
    密码加密（PBKDF2-SHA256，随机盐），格式 pbkdf2_sha256$迭代次数$盐$摘要
    """
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', passwd.encode('utf-8'), bytes.fromhex(salt), iterations).hex()
    return f"{PASSWD_SCHEME}${iterations}${salt}${digest}"


def verifyPasswd(passwd, stored):
    """
    校验密码，兼容旧版 MD5 摘要
    """
    if not stored or passwd is None:
        return False
    if stored.startswith(PASSWD_SCHEME + '$'):
        try:
            _, iterations, salt, digest = stored.split('$', 3)
            actual = hashlib.pbkdf2_hmac('sha256', passwd.encode('utf-8'), bytes.fromhex(salt),
                                         int(iterations)).hex()
        except (ValueError, TypeError):
            return False
        return hmac.compare_digest(actual, digest)
    return hmac.compare_digest(passwd2md5(passwd), stored)


def passwdNeedsRehash(stored):
    if not stored or not stored.startswith(PASSWD_SCHEME + '$'):
        return True
    try:
        return int(stored.split('$', 3)[1]) < PASSWD_ITERATIONS
    except (ValueError, IndexError):
        return True


def sessionVersion(user):
    """
    会话版本：由用户与当前密码摘要派生，写入 Cookie 代替密码摘要；改密后旧会话自动失效
    """
    from common.config import getConfig
    secret = getConfig()['server']['passwdStr'].encode('utf-8')
    message = f"{user['id']}:{user['userName']}:{user['passwd']}".encode('utf-8')
    return hmac.new(secret, message, hashlib.sha256).hexdigest()[:32]


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
        with open(fileName, 'r', encoding='utf-8') as file:
            fnData = file.read()
    else:
        fnData = default
        with open(fileName, 'w', encoding='utf-8') as file:
            file.write(default)
    return fnData
