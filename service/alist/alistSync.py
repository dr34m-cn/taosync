"""
@Author：dr34m
@Date  ：2024/7/9 12:14 
"""
from service.alist.alistService import getClientById


def getSrcMore(src, dst, sizeCheck=True):
    """
    获取来源比目标多的文件
    :param src: 来源
    :param dst: 目标
    :param sizeCheck: 是否校验文件大小
    对于删除不需要检验，因为对于同文件名不同大小的文件，复制会覆盖它，不需要删除
    删除可能导致刚复制的文件被删除（实测不会，猜测删除是瞬间操作，会比复制更快进行）
    :return:
    """
    moreFile = {}
    for key in src.keys():
        if key not in dst:
            moreFile[key] = src[key]
        elif not key.endswith('/'):
            if sizeCheck and src[key] != dst[key]:
                moreFile[key] = src[key]
        else:
            moreChild = getSrcMore(src[key], dst[key], sizeCheck)
            if moreChild:
                moreFile[key] = moreChild
    return moreFile


def copyFiles(srcPath, dstPath, client, files, copyHook=None):
    """
    复制文件
    :param srcPath: 来源路径
    :param dstPath: 目标路径
    :param client: 客户端
    :param files: 文件
    :param copyHook: 复制文件回调，（srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None）
    """
    for key in files.keys():
        if key.endswith('/'):
            copyFiles(f'{srcPath}{key}', f'{dstPath}{key}', client, files[key], copyHook)
        else:
            try:
                alistTaskId = client.copyFile(srcPath, dstPath, key)
                if copyHook is not None:
                    copyHook(srcPath, dstPath, key, files[key], alistTaskId=alistTaskId)
            except Exception as e:
                if copyHook is not None:
                    copyHook(srcPath, dstPath, key, files[key], status=7, errMsg=str(e))


def delFiles(dstPath, client, files, delHook=None):
    """
    删除文件
    :param dstPath: 目标目录
    :param client: 客户端
    :param files: 文件
    :param delHook: 删除文件回调，（dstPath, name, size, status=2:2-成功、7-失败, errMsg=None）
    """
    for key in files.keys():
        if key.endswith('/'):
            delFiles(f'{dstPath}{key}', client, files[key], delHook)
        else:
            try:
                client.deleteFile(dstPath, [key])
                if delHook is not None:
                    delHook(dstPath, key, files[key])
            except Exception as e:
                if delHook is not None:
                    delHook(dstPath, key, files[key], status=7, errMsg=str(e))


def sync(srcPath, dstPath, alistId, speed=0, method=0, copyHook=None, delHook=None):
    """
    同步方法，仅支持alist
    :param srcPath: 来源路径
    :param dstPath: 目标路径，多个以英文冒号[:]分隔
    :param alistId: 客户端id
    :param speed: 速度，0-标准，1-快速
    :param method: 0-仅新增，1-全同步
    :param copyHook: 复制文件回调，（srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None）
    :param delHook: 删除文件回调，（dstPath, name, size, status=2:2-成功、7-失败, errMsg=None）
    """
    client = getClientById(alistId)
    if not srcPath.endswith('/'):
        srcPath = srcPath + '/'
    srcFiles = client.allFileList(srcPath)
    dstPathList = dstPath.split(':')
    for dstItem in dstPathList:
        if not dstItem.endswith('/'):
            dstItem = dstItem + '/'
        dstFiles = client.allFileList(dstItem, speed == 0)
        needCopy = getSrcMore(srcFiles, dstFiles)
        copyFiles(srcPath, dstItem, client, needCopy, copyHook)
        if method == 1:
            needDel = getSrcMore(dstFiles, srcFiles, False)
            delFiles(dstItem, client, needDel, delHook)
