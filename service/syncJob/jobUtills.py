import os
from hashlib import md5


def getMd5(string):
    salt = 'afea'
    encodeStr = str(string) + salt
    obj = md5()
    obj.update(encodeStr.encode("utf-8"))
    return obj.hexdigest()

# 加密和解密场景下，通过创建文件夹在另一端是否能能找到判断配置是否正确
def alistAndLocalPathMatch(job,client):

    tempRootFix = '#TEMP_ENPT/'
    # 加密和解密场景下，通过创建文件夹在另一端是否能能找到判断配置是否正确
    encryptFlag = job['encryptFlag']
    if encryptFlag == 1:
        alistPath = job['srcPath']
    elif encryptFlag == 2:
        alistPath = job['dstPath']

    localPath = job['localPath']

    dirName = getMd5(localPath)

    alistPath = alistPath + tempRootFix + dirName
    locaPath = localPath + tempRootFix + dirName
    client.mkdir(alistPath)
    flag = os.path.exists(locaPath)
    if flag:
        try:
            os.removedirs(locaPath)
        except Exception as e:
            raise e
    else:
        if encryptFlag == 1:
            msg = '本地目录和Alist源目录不匹配'
        else:
            msg = '本地目录和Alist目标目录不匹配'
        raise RuntimeError(msg)
