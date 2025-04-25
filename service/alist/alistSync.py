"""
@Author：dr34m
@Date  ：2024/7/9 12:14 
"""
import logging
import os
import time

import igittigitt
from gmssl.sm4 import SM4_ENCRYPT, SM4_DECRYPT

from service.alist.alistService import getClientById
from service.encrypt.encrypt import SM4FileCrypto


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

#pavel 20250422 增加是否加密和本地路径用于本地加密
def copyFiles(encryptFlag,encryptKey,iv,localRootPath,srcRootPath,dstRootPath,srcPath, dstPath, client, files, copyHook=None, job=None):
    """
    复制文件
    :param encryptFlag: 是否加密
    :param encryptKey:加密密码
    :param localRootPath: 本地路径
    :param srcRootPath: alist任务来源路径
    :param dstRootPath: alist任务目标路径
    :param srcPath: 来源路径
    :param dstPath: 目标路径
    :param client: 客户端
    :param files: 文件
    :param copyHook: 复制文件回调，（srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None）
    :param job: 作业
    """
    #临时文件夹
    tempRootFix = '#TEMP_ENPT/'

    for key in files.keys():
        if job is not None and job['enable'] == 0:
            return
        if key.endswith('/'):
            copyFiles(encryptFlag,encryptKey,iv,localRootPath,srcRootPath,dstRootPath,f'{srcPath}{key}', f'{dstPath}{key}', client, files[key], copyHook, job)
        else:
            try:
                if(encryptFlag == 1):
                    #来源文件对应的本地文件夹
                    localSrcPath = srcPath.replace(srcRootPath,localRootPath)

                    #加密文件临时文件夹
                    tempPath = localSrcPath + tempRootFix
                    if not os.path.exists(tempPath):
                        os.mkdir(tempPath)

                    #来源文件对应的本地文件路径
                    localFile = localSrcPath+key

                    #加密文件临时路径
                    tempFile = tempPath + key

                    #执行加密，如有重名文件先清除
                    if os.path.exists(localFile):
                        if os.path.exists(tempFile):
                            os.remove(tempFile)
                        print(f'开始加密：{localFile}{time.asctime()}')
                        cipher = SM4FileCrypto(encryptKey,iv)
                        cipher.encrypt_file(localFile,tempFile)
                        print(f'完成加密：{localFile}{time.asctime()}')
                    #在asist中查询加密文件是否存在 todo 是否能省略？
                        res = client.filePathList(srcPath+tempRootFix)
                        if res is None:
                            continue
                    #将alist来源文件路径替换成加密临时文件路径
                    if os.path.exists(tempFile):
                        srcPath = srcPath + tempRootFix

                if(encryptFlag == 2):
                    originalDstPath = dstPath
                    # alist目标路径临时文件夹
                    dstPath = dstPath + tempRootFix

                #解决复制文件时多层目标路径出错的问题
                client.mkdir(dstPath)
                #执行复制
                alistTaskId = client.copyFile(srcPath, dstPath, key)
                if copyHook is not None:
                    if alistTaskId:
                        copyHook(srcPath, dstPath, key, files[key], alistTaskId=alistTaskId)
                    else:
                        # 本地对本地的任务，不会产生alistTaskId，直接认为其成功
                        copyHook(srcPath, dstPath, key, files[key], status=2)

                if (encryptFlag == 2):
                    # alist目标路径临时文件夹 对应的本地文件夹
                    tempPath = dstPath.replace(dstRootPath, localRootPath)
                    # alist目标路径 对应的本地文件夹
                    localDstPath = originalDstPath.replace(dstRootPath, localRootPath)
                    if not os.path.exists(localDstPath):
                        os.mkdir(localDstPath)
                    tempFile = tempPath + key
                    dstFile = localDstPath+key

                    #删除未处理完成的目标文件
                    if os.path.exists(dstFile):
                        os.remove(dstFile)
                    cipher = SM4FileCrypto(encryptKey,iv)
                    print(f'开始解密：{tempFile}')
                    cipher.decrypt_file(tempFile, dstFile)
                    print(f'完成解密：{tempFile}')

                #删除临时文件和临时文件夹
                if os.path.exists(tempFile):
                    os.remove(tempFile)
                if os.path.exists(tempPath):
                    os.removedirs(tempPath)

            except Exception as e:
                logger = logging.getLogger()
                logger.exception(e)
                if copyHook is not None:
                    copyHook(srcPath, dstPath, key, files[key], status=7, errMsg=str(e))


def delFiles(dstPath, client, files, delHook=None, job=None):
    """
    删除文件
    :param dstPath: 目标目录
    :param client: 客户端
    :param files: 文件
    :param delHook: 删除文件回调，（dstPath, name, size, status=2:2-成功、7-失败, errMsg=None）
    :param job: 作业
    """
    for key in files.keys():
        if job is not None and job['enable'] == 0:
            return
        if key.endswith('/'):
            delFiles(f'{dstPath}{key}', client, files[key], delHook, job)
        else:
            try:
                client.deleteFile(dstPath, [key])
                if delHook is not None:
                    delHook(dstPath, key, files[key])
            except Exception as e:
                if delHook is not None:
                    delHook(dstPath, key, files[key], status=7, errMsg=str(e))


# pavel 20250422 增加是否加密和本地路径用于本地加密
def sync(encryptFlag,encryptKey,localRootPath,srcPath, dstPath, alistId, speed=0, method=0, copyHook=None, delHook=None, job=None):
    """
    同步方法，仅支持alist
    :param encryptFlag: 是否加密
    :param encryptKey:加密密码
    :param localRootPath: 本地路径
    :param srcPath: 来源路径
    :param dstPath: 目标路径，多个以英文冒号[:]分隔
    :param alistId: 客户端id
    :param speed: 速度，0-标准，1-快速，2-低速
    :param method: 0-仅新增，1-全同步
    :param copyHook: 复制文件回调，（srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None）
    :param delHook: 删除文件回调，（dstPath, name, size, status=2:2-成功、7-失败, errMsg=None）
    :param job: 作业
    """

    if encryptFlag != 0:
        if len(encryptKey) != 32:
            raise ValueError("密码格式不对")
        encodeKey = encryptKey[6:22].upper().encode('utf-8')
        iv = encryptKey[16:32].upper().encode('utf-8')


    jobExclude = job['exclude']
    parser = None
    if jobExclude is not None:
        parser = igittigitt.IgnoreParser()
        for exItem in jobExclude.split(':'):
            parser.add_rule(exItem, '/')
    client = getClientById(alistId)
    if not srcPath.endswith('/'):
        srcPath = srcPath + '/'
    srcFiles = client.allFileList(srcPath, parser=parser)
    dstPathList = dstPath.split(':')
    for dstItem in dstPathList:
        if not dstItem.endswith('/'):
            dstItem = dstItem + '/'
        dstFiles = client.allFileList(dstItem, speed, parser=parser)
        needCopy = getSrcMore(srcFiles, dstFiles)
        if job is not None and job['enable'] == 0:
            return
        copyFiles(encryptFlag,encodeKey,iv,localRootPath,srcPath,dstPath,srcPath, dstItem, client, needCopy, copyHook)
        if method == 1:
            needDel = getSrcMore(dstFiles, srcFiles, False)
            delFiles(dstItem, client, needDel, delHook, job)
