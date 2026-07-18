"""
@Author：dr34m
@Date  ：2024/7/11 12:14 
"""
import itertools
import json
import logging
import posixpath
import threading
import time
from collections import defaultdict

from apscheduler.schedulers.background import BackgroundScheduler
from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

from common.LNG import G
from mapper import jobMapper
from service.engine import engineService
from service.syncJob import taskService


def isFileSizeAllowed(fileSize, minFileSize=None, maxFileSize=None):
    if minFileSize is not None and fileSize < minFileSize:
        return False
    if maxFileSize is not None and fileSize > maxFileSize:
        return False
    return True


def normalizeVirtualPath(path):
    value = str(path).replace('\\', '/')
    # Virtual paths can resolve to case-insensitive Local/SMB backends. A
    # conservative case-fold prevents aliases from bypassing overlap checks.
    return posixpath.normpath('/' + value.lstrip('/')).casefold()


def virtualPathsOverlap(firstPath, secondPath):
    first = normalizeVirtualPath(firstPath)
    second = normalizeVirtualPath(secondPath)
    return (first == second
            or first.startswith(second.rstrip('/') + '/')
            or second.startswith(first.rstrip('/') + '/'))


class CopyItem:
    def __init__(self, srcPath, dstPath, fileName, fileSize, method, jobTask):
        self.jobTask = jobTask
        self.alistClient = self.jobTask.alistClient
        self.taskId = self.jobTask.taskId
        self.srcPath = srcPath
        self.dstPath = dstPath
        self.fileName = fileName
        self.fileSize = fileSize
        self.copyType = 0 if method < 2 else 2
        self.alistTaskId = None
        self.status = 0
        self.progress = 0.0
        self.errMsg = None
        self.createTime = int(time.time())
        self.doingKey = None

    def doByThread(self):
        doThread = threading.Thread(target=self.doIt)
        doThread.start()

    def doIt(self):
        try:
            if self.jobTask.breakFlag:
                self.status = 4
            else:
                self.alistTaskId = self.alistClient.copyFile(self.srcPath, self.dstPath, self.fileName)
        except Exception as e:
            self.errMsg = str(e)
            self.status = 7
        else:
            if self.alistTaskId is None:
                self.status = 2
            elif self.status != 4:
                self.checkAndGetStatus()
        self.endIt()

    def checkAndGetStatus(self):
        """
        不断检查状态并更新
        :return:
        """
        while True:
            if self.jobTask.breakFlag:
                self.status = 4
                if self.alistTaskId is not None:
                    try:
                        self.alistClient.copyTaskCancel(self.alistTaskId)
                        self.alistClient.copyTaskDelete(self.alistTaskId)
                    except Exception as e:
                        self.status = 7
                        self.errMsg = str(e)
                break
            cuTime = time.time()
            time.sleep(0.61 if cuTime - self.jobTask.lastWatching < 3 else 2.93)
            try:
                taskInfo = self.alistClient.taskInfo(self.alistTaskId)
            except Exception as e:
                logger = logging.getLogger()
                logger.exception(e)
                eMsg = str(e)
                if '404' in eMsg:
                    eMsg = (G('task_may_delete'))
                taskInfo = {
                    'state': 7,
                    'progress': None,
                    'error': eMsg
                }
            if taskInfo['state'] == self.status and taskInfo['progress'] == self.progress:
                continue
            self.status = taskInfo['state']
            self.progress = taskInfo['progress']
            self.errMsg = taskInfo['error'] if taskInfo['error'] else None
            # 删除结束的任务
            if taskInfo['state'] in [2, 4, 7]:
                try:
                    self.alistClient.copyTaskDelete(self.alistTaskId)
                    break
                except Exception:
                    break

    def endIt(self):
        # Move-mode source files are deleted by JobTask only after every target
        # copy has succeeded. Deleting here races when a job has multiple targets.
        self.jobTask.copyHook(self.srcPath, self.dstPath, self.fileName, self.fileSize, self.alistTaskId, self.status,
                              errMsg=self.errMsg, copyType=self.copyType, createTime=self.createTime)
        del self.jobTask.doing[self.doingKey]


class JobTask:
    def __init__(self, taskId, vm):
        """
        作业任务类
        :param taskId: 任务id
        :param vm: 作业上下文
        """
        self.taskId = taskId
        self.jobClient = vm
        self.job = self.jobClient.job
        self.alistClient = engineService.getClientById(self.job['alistId'])
        self.createTime = time.time()
        # 已完成（包含成功或者失败）
        self.finish = []
        # 已经提交到alist的任务
        self.doing = {}
        # 等待提交到alist的任务
        self.waiting = []
        # 上次查看详情的时间戳，低于3秒表示正在看，在看则快速检查状态，否则低速检查以节约开销
        self.lastWatching = 0.0
        # 队列序号，用作复制任务的doingKey
        self.queueNum = 0
        # sync全部任务加入队列标识
        self.scanFinish = False
        # 首个文件开始同步时间
        self.firstSync = None
        # 手动中止标识
        self.breakFlag = False
        # A complete source-tree view, keyed by normalized relative path.
        self.sourceSnapshot = {}
        self.sourceScanAttempted = False
        self.sourceScanFailed = False
        self.previousSourceSnapshot = None
        self.sourceSnapshotIdentity = jobMapper.sourceSnapshotIdentity(self.job)
        self.currentTasks = {}
        self.syncThread = threading.Thread(target=self.sync)
        self.submitThread = threading.Thread(target=self.taskSubmit)

    def start(self):
        self.syncThread.start()
        self.submitThread.start()

    def getCurrent(self):
        """
        总结并返回详情（高实时性）
        :return: {
            'scanFinish': True,
            'doingTask': [{
                'srcPath': 来源目录,
                'dstPath': 目标目录,
                'fileName': 文件名,
                'fileSize': 文件大小,
                'status': 状态,
                'type': 方式，0-复制（对于目录则是创建），1-删除，2-移动,
                'progress': 进度,
                'errMsg': 错误信息,
                'createTime': 创建时间
            }],
            'createTime': int(self.createTime),
            'duration': int(self.lastWatching - self.createTime),
            'firstSync': int(self.firstSync) if self.firstSync is not None else None,
            'num': {
                'wait': 0,
                'running': 1,
                'success': 2,
                'fail': 7,
                'other': 0
            },
            'size': {
                'wait': 0,
                'running': 1,
                'success': 2,
                'fail': 7,
                'other': 0
            }
        }
        """
        self.lastWatching = time.time()
        waits = [{
            'srcPath': waitItem.srcPath,
            'dstPath': waitItem.dstPath,
            'isPath': 0,
            'fileName': waitItem.fileName,
            'fileSize': waitItem.fileSize,
            'status': waitItem.status,
            'type': waitItem.copyType,
            'progress': waitItem.progress,
            'errMsg': waitItem.errMsg,
            'createTime': waitItem.createTime
        } for waitItem in self.waiting]
        dos = [{
            'srcPath': doItem.srcPath,
            'dstPath': doItem.dstPath,
            'isPath': 0,
            'fileName': doItem.fileName,
            'fileSize': doItem.fileSize,
            'status': doItem.status,
            'type': doItem.copyType,
            'progress': doItem.progress,
            'errMsg': doItem.errMsg,
            'createTime': doItem.createTime
        } for doItem in self.doing.values()]
        allTask = list(itertools.chain(waits, dos, self.finish))
        keyValSpace = {
            'wait': 0,
            'running': 1,
            'success': 2,
            'fail': 7,
            'other': -1
        }
        currentTasks = {}
        for val in keyValSpace.values():
            currentTasks[val] = []
        # 其他类型数组
        otk = []
        otkStatus = [3, 4, 5, 6, 8, 9]
        grouped = defaultdict(list)
        for taskItem in allTask:
            grouped[taskItem['status']].append(taskItem)
        for status, tasks in grouped.items():
            tasks.sort(key=lambda x: x['createTime'])
            if status in otkStatus:
                otk.extend(tasks)
            else:
                currentTasks[status] = tasks
        currentTasks[-1] = otk
        self.currentTasks = currentTasks
        result = {
            'scanFinish': self.scanFinish,
            'doingTask': currentTasks[1],
            'createTime': int(self.createTime),
            'duration': int(self.lastWatching - self.createTime),
            'firstSync': int(self.firstSync) if self.firstSync is not None else None,
            'num': {},
            'size': {}
        }
        for key, val in keyValSpace.items():
            result['num'][key] = len(currentTasks[val])
            result['size'][key] = sum(
                item['fileSize'] for item in currentTasks[val] if item['fileSize'] is not None and item['type'] != 1)
        return result

    def getCurrentByStatus(self, status):
        return self.currentTasks[status]

    def taskSubmit(self):
        """
        队列检验与提交
        :return:
        """
        while True:
            if self.breakFlag:
                break
            time.sleep(0.5)
            doingNums = len(self.doing.keys())
            waitingNums = len(self.waiting)
            if not self.scanFinish or doingNums != 0 or waitingNums != 0:
                while doingNums < 20:
                    if self.breakFlag:
                        break
                    if waitingNums == 0:
                        break
                    else:
                        if self.firstSync is None:
                            self.firstSync = time.time()
                        self.queueNum += 1
                        self.doing[self.queueNum] = self.waiting.pop(0)
                        self.doing[self.queueNum].doingKey = self.queueNum
                        self.doing[self.queueNum].doByThread()
                        doingNums = len(self.doing.keys())
                        waitingNums = len(self.waiting)
            else:
                break
        tryTime = 0
        while len(self.doing.keys()) > 0:
            tryTime += 1
            time.sleep(.5)
            if tryTime > 3:
                break
        try:
            if self.job.get('method') == 2 and self._allOperationsSuccessful():
                self.finalizeMove()
            self.commitSourceSnapshot()
            if self.finish:
                jobMapper.addJobTaskItemMany(self.finish)
            self.updateTaskStatus()
        finally:
            self.jobClient.finishRun(self)

    def _allOperationsSuccessful(self):
        return (not self.breakFlag
                and self.sourceScanAttempted
                and not self.sourceScanFailed
                and all(item['status'] == 2 for item in self.finish))

    @staticmethod
    def normalizeRoot(path):
        path = str(path)
        return path if path.endswith('/') else path + '/'

    @staticmethod
    def entryLocation(rootPath, relativePath):
        rootPath = JobTask.normalizeRoot(rootPath)
        if '/' not in relativePath:
            return rootPath, relativePath
        parent, name = relativePath.rsplit('/', 1)
        return rootPath + parent + '/', name

    def finalizeMove(self):
        """Delete each eligible source file once after all targets are ready."""
        freshSourceDirectories = {}
        destinationRoots = {
            self.normalizeRoot(item) for item in self.job['dstPath'].split(':')
        }
        for entry in sorted(self.sourceSnapshot.values(), key=lambda item: item['path']):
            if self.breakFlag or entry['isDir'] or not self.fileSizeAllowed(entry['size']):
                continue
            srcPath, fileName = self.entryLocation(self.job['srcPath'], entry['path'])
            matching = [item for item in self.finish
                        if item['type'] == 2 and item['srcPath'] == srcPath and item['fileName'] == fileName]
            expectedDestinations = {
                self.entryLocation(root, entry['path'])[0]
                for root in destinationRoots
            }
            deliveredDestinations = {
                self.normalizeRoot(item['dstPath'])
                for item in matching if item.get('dstPath')
            }
            if (len(matching) != len(deliveredDestinations)
                    or deliveredDestinations != expectedDestinations):
                self.markMoveDeleteFailure(
                    matching, srcPath, fileName, entry['size'], G('move_delivery_incomplete')
                )
                continue
            try:
                if srcPath not in freshSourceDirectories:
                    _entries, details = self.readDirectory(srcPath, 0, 0)
                    freshSourceDirectories[srcPath] = details
                freshEntry = freshSourceDirectories[srcPath].get(fileName)
                freshSize = None if freshEntry is None else freshEntry.get('size')
            except Exception as e:
                self.markMoveDeleteFailure(matching, srcPath, fileName, entry['size'], str(e))
                continue
            if freshEntry is not None and (
                    freshEntry.get('isDir') or freshSize != entry['size']):
                self.markMoveDeleteFailure(
                    matching, srcPath, fileName, entry['size'], G('source_changed_during_move')
                )
                continue
            if freshEntry is None:
                if not matching:
                    self.copyHook(srcPath, None, fileName, entry['size'], status=2, copyType=2)
                continue
            expectedFingerprint = entry.get('fingerprint')
            if expectedFingerprint is None:
                self.markMoveDeleteFailure(
                    matching, srcPath, fileName, entry['size'], G('source_version_unavailable')
                )
                continue
            if freshEntry.get('fingerprint') != expectedFingerprint:
                self.markMoveDeleteFailure(
                    matching, srcPath, fileName, entry['size'], G('source_changed_during_move')
                )
                continue
            try:
                self.alistClient.deleteFile(srcPath, [fileName], 0)
            except Exception as e:
                errMsg = G('copy_success_but_delete_fail').format(str(e))
                self.markMoveDeleteFailure(matching, srcPath, fileName, entry['size'], errMsg)
            else:
                if not matching:
                    self.copyHook(srcPath, None, fileName, entry['size'], status=2, copyType=2)

    def markMoveDeleteFailure(self, matching, srcPath, fileName, fileSize, errMsg):
        if matching:
            for item in matching:
                item['status'] = 7
                item['errMsg'] = errMsg
        else:
            self.copyHook(srcPath, None, fileName, fileSize, status=7,
                          errMsg=errMsg, copyType=2)

    def commitSourceSnapshot(self):
        if not self._allOperationsSuccessful():
            return
        entries = list(self.sourceSnapshot.values())
        if self.job.get('method') == 2:
            # Successfully moved files no longer exist at the source. Retain
            # directories and size-filtered files in the committed view.
            entries = [entry for entry in entries
                       if entry['isDir'] or not self.fileSizeAllowed(entry['size'])]
        try:
            expectedIdentity = getattr(
                self, 'sourceSnapshotIdentity', jobMapper.sourceSnapshotIdentity(self.job)
            )
            jobMapper.replaceSourceSnapshot(
                self.job['id'], entries, expectedIdentity=expectedIdentity
            )
        except Exception as e:
            logger = logging.getLogger()
            logger.exception(e)
            self.copyHook(self.normalizeRoot(self.job['srcPath']), None, None, None,
                          status=7, errMsg=str(e), isPath=1)

    def copyHook(self, srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None, isPath=0,
                 copyType=0, createTime=int(time.time())):
        """
        复制文件回调
        :param srcPath: 来源目录
        :param dstPath: 目标目录
        :param name: 文件名
        :param size: 文件大小
        :param alistTaskId: alist任务id
        :param status: 0-等待中，1-运行中，2-成功，3-取消中，4-已取消，5-出错（将重试），6-失败中，
                        7-已失败，8-等待重试中，9-等待重试回调执行中，10-目录扫描失败，11-目录创建失败
        :param errMsg: 错误信息
        :param isPath: 是否是目录，0-文件，1-目录
        :param copyType: 0-复制，2-移动
        :param createTime:
        """
        self.finish.append({
            'taskId': self.taskId,
            'srcPath': srcPath,
            'dstPath': dstPath,
            'isPath': isPath,
            'fileName': name,
            'fileSize': size,
            'type': copyType,
            'alistTaskId': alistTaskId,
            'status': status,
            'errMsg': errMsg,
            'createTime': createTime
        })

    def delHook(self, dstPath, name, size, status=2, errMsg=None, isPath=0, createTime=int(time.time())):
        """
        删除文件回调
        :param dstPath: 目标目录
        :param name: 文件名
        :param size: 文件大小
        :param status: 2-成功、7-失败
        :param errMsg: 错误信息
        :param isPath: 是否是目录，0-文件，1-目录
        :param createTime: 创建时间
        """
        self.finish.append({
            'taskId': self.taskId,
            'srcPath': None,
            'dstPath': dstPath,
            'isPath': isPath,
            'fileName': name,
            'fileSize': size,
            'type': 1,
            'alistTaskId': None,
            'status': status,
            'errMsg': errMsg,
            'createTime': createTime
        })

    def sync(self):
        """
        同步方法
        """
        srcPath = self.normalizeRoot(self.job['srcPath'])
        jobExclude = self.job['exclude']
        spec = None
        if jobExclude is not None:
            spec = PathSpec.from_lines(GitWildMatchPattern, jobExclude.split(':'))
        dstPathList = [self.normalizeRoot(item) for item in self.job['dstPath'].split(':')]
        try:
            pathsOverlap = getattr(self.alistClient, 'pathsOverlap', virtualPathsOverlap)
            if any(pathsOverlap(srcPath, dstPath) for dstPath in dstPathList):
                raise ValueError(G('source_target_overlap'))
            storedSnapshot = jobMapper.getSourceSnapshot(self.job['id'])
            if storedSnapshot['meta']['initialized'] == 1:
                self.previousSourceSnapshot = {
                    item['path']: item for item in storedSnapshot['entries']
                }
            else:
                self.previousSourceSnapshot = None
            if self.job.get('sourceMode') == 1 and storedSnapshot['meta']['initialized'] == 1:
                if self.scanSourceTree(srcPath, spec, srcPath):
                    self.syncFromSourceSnapshot(storedSnapshot['entries'], dstPathList)
            else:
                for index, dstItem in enumerate(dstPathList):
                    self.syncWithHave(srcPath, dstItem, spec, srcPath, dstItem, index == 0)
        except Exception as e:
            logger = logging.getLogger()
            logger.exception(e)
            self.sourceScanFailed = True
            self.copyHook(srcPath, None, None, None, status=7, errMsg=str(e), isPath=1)
        finally:
            self.scanFinish = True

    def scanSourceTree(self, path, spec, rootPath):
        """Scan the complete source tree without reading any target directory."""
        if self.breakFlag:
            return False
        try:
            entries = self.listDir(path, True, spec, rootPath)
        except Exception:
            return False
        for name in entries:
            if name.endswith('/') and not self.scanSourceTree(path + name, spec, rootPath):
                return False
        return not self.breakFlag and not self.sourceScanFailed

    def syncFromSourceSnapshot(self, storedEntries, dstPathList):
        """Plan a subsequent run from the current and committed source views."""
        previous = {
            item['path']: {
                'path': item['path'],
                'isDir': int(item['isDir']),
                'size': item['size'],
                'fingerprint': item.get('fingerprint'),
            }
            for item in storedEntries
        }
        current = self.sourceSnapshot

        changedFiles = [entry for path, entry in current.items()
                        if not entry['isDir']
                        and self.fileSizeAllowed(entry['size'])
                        and (self.job['method'] == 2
                             or self.sourceEntryChanged(previous.get(path), entry))]
        newDirectories = [entry for path, entry in current.items()
                          if entry['isDir']
                          and (path not in previous or not previous[path]['isDir'])]

        removed = [entry for path, entry in previous.items()
                   if path not in current or current[path]['isDir'] != entry['isDir']]

        for dstRoot in dstPathList:
            failedDirectoryPrefixes = []
            if self.job['method'] == 1:
                self.deleteSnapshotEntries(dstRoot, removed)

            for entry in sorted(newDirectories, key=lambda item: (item['path'].count('/'), item['path'])):
                if any(self.pathWithin(entry['path'], prefix) for prefix in failedDirectoryPrefixes):
                    continue
                dstPath = dstRoot + entry['path'] + '/'
                srcPath = self.normalizeRoot(self.job['srcPath']) + entry['path'] + '/'
                status = 2
                errMsg = None
                try:
                    self.alistClient.mkdir(dstPath, self.job['scanIntervalT'])
                except Exception as e:
                    status = 7
                    errMsg = str(e)
                    failedDirectoryPrefixes.append(entry['path'])
                self.copyHook(srcPath, dstPath, None, None, status=status, errMsg=errMsg, isPath=1)

            for entry in changedFiles:
                parentPath, fileName = self.entryLocation(dstRoot, entry['path'])
                if any(self.pathWithin(entry['path'], prefix) for prefix in failedDirectoryPrefixes):
                    continue
                srcPath, _ = self.entryLocation(self.job['srcPath'], entry['path'])
                self.copyFile(srcPath, parentPath, fileName, entry['size'])

    @staticmethod
    def pathWithin(path, prefix):
        return path == prefix or path.startswith(prefix + '/')

    @staticmethod
    def sourceEntryChanged(previous, current):
        if (previous is None or previous.get('isDir')
                or previous.get('size') != current.get('size')):
            return True
        previousFingerprint = previous.get('fingerprint')
        currentFingerprint = current.get('fingerprint')
        return ((previousFingerprint is not None or currentFingerprint is not None)
                and previousFingerprint != currentFingerprint)

    def sourceFileChangedSinceSnapshot(self, srcPath, srcRootPath, fileName):
        previous = getattr(self, 'previousSourceSnapshot', None)
        if previous is None:
            return False
        relativeBase = (
            srcPath[len(srcRootPath):].strip('/')
            if srcPath.startswith(srcRootPath) else ''
        )
        relativePath = '/'.join(
            item for item in (relativeBase, fileName) if item
        )
        current = self.sourceSnapshot.get(relativePath)
        previousEntry = previous.get(relativePath)
        return (current is not None and previousEntry is not None
                and self.sourceEntryChanged(previousEntry, current))

    def deleteSnapshotEntries(self, dstRoot, removedEntries):
        """Apply source removals known from the prior snapshot to a full-sync target."""
        # Without a target scan, a removed directory may contain excluded or
        # independently-created target files. Delete only tracked files and
        # retain directory shells.
        for entry in removedEntries:
            if entry['isDir'] or not self.fileSizeAllowed(entry['size']):
                continue
            parentPath, name = self.entryLocation(dstRoot, entry['path'])
            self.delFile(parentPath, name, entry['size'])

    def copyFile(self, srcPath, dstPath, fileName, fileSize):
        """
        复制文件
        vm.job['method']: 0-仅新增，1-全同步，2-移动模式
        vm.job['copyHook']: 复制文件回调，（srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None, isPath=0）
        vm.job['delHook']: 删除文件回调，（dstPath, name, size, status=2:2-成功、7-失败, errMsg=None, isPath=0）
        :param srcPath: 源目录
        :param dstPath: 目标目录
        :param fileName: 文件名
        :param fileSize: 文件大小
        :return:
        """
        if self.breakFlag:
            return
        copyItem = CopyItem(srcPath, dstPath, fileName, fileSize, self.job['method'], self)
        self.waiting.append(copyItem)

    def hasFileSizeFilter(self):
        return self.job.get('minFileSize') is not None or self.job.get('maxFileSize') is not None

    def fileSizeAllowed(self, fileSize):
        return isFileSizeAllowed(fileSize, self.job.get('minFileSize'), self.job.get('maxFileSize'))

    def delFile(self, path, fileName, size):
        """
        删除文件（或目录）
        self.job['method']: 0-仅新增，1-全同步，2-移动模式
        self.copyHook: 复制文件回调，（srcPath, dstPath, name, size, alistTaskId=None, status=0, errMsg=None, isPath=0, createTime）
        self.delHook: 删除文件回调，（dstPath, name, size, status=2:2-成功、7-失败, errMsg=None, isPath=0, createTime）
        :param path: 所在路径
        :param fileName: 文件名（或目录名）
        :param size: 大小（文件）或空对象（目录）
        :return:
        """
        if self.breakFlag:
            return
        isPath = fileName.endswith('/')
        status = 2
        errMsg = None
        createTime = int(time.time())
        try:
            self.alistClient.deleteFile(path, [fileName if not isPath else fileName[:-1]], self.job['scanIntervalT'])
        except Exception as e:
            status = 7
            errMsg = str(e)
        self.delHook(path, fileName, None if isPath else size, status, errMsg, isPath, createTime)

    def listDir(self, path, firstDst, spec, rootPath, isSrc=True):
        """
        列出目录
        self.job['useCacheT']: 扫描目标目录时，是否使用缓存，0-不使用，1-使用
        self.job['scanIntervalT']: 目标目录扫描间隔，单位秒
        self.job['useCacheS']: 扫描源目录时，是否使用缓存，0-不使用，1-使用
        self.job['scanIntervalS']: 源目录扫描间隔，单位秒
        :param path:
        :param firstDst: 是否是第一个目标目录（如果是，将完整扫描源目录，否则使用缓存扫描源目录）
        :param spec:
        :param rootPath:
        :param isSrc:
        :return:
        """
        useCache = 1 if isSrc and not firstDst else self.job[f"useCache{'S' if isSrc else 'T'}"]
        scanInterval = self.job[f"scanInterval{'S' if isSrc else 'T'}"]
        try:
            entries, details = self.readDirectory(
                path, useCache, scanInterval, spec, rootPath
            )
            if isSrc and firstDst:
                self.recordSourceEntries(path, rootPath, entries, details)
            return entries
        except Exception as e:
            logger = logging.getLogger()
            errMsg = G('scan_error').format(G('src' if isSrc else 'dst'), str(e))
            logger.error(errMsg)
            logger.exception(e)
            if isSrc and firstDst:
                self.sourceScanAttempted = True
                self.sourceScanFailed = True
            self.copyHook(path if isSrc else None, None if isSrc else path, None, None, status=7, errMsg=errMsg,
                          isPath=1)
            raise e

    def readDirectory(self, path, useCache=0, scanInterval=0, spec=None, rootPath=None):
        detailApi = getattr(self.alistClient, 'fileListDetailApi', None)
        if callable(detailApi):
            rawDetails = detailApi(path, useCache, scanInterval, spec, rootPath)
            details = {}
            entries = {}
            for name, rawDetail in rawDetails.items():
                detail = rawDetail if isinstance(rawDetail, dict) else {}
                isDirectory = bool(detail.get('isDir', name.endswith('/')))
                size = None if isDirectory else detail.get('size')
                details[name] = {
                    'isDir': 1 if isDirectory else 0,
                    'size': size,
                    'fingerprint': detail.get('fingerprint'),
                }
                entries[name] = {} if isDirectory else size
            return entries, details

        entries = self.alistClient.fileListApi(
            path, useCache, scanInterval, spec, rootPath
        )
        details = {
            name: {
                'isDir': 1 if name.endswith('/') else 0,
                'size': None if name.endswith('/') else size,
                'fingerprint': None,
            }
            for name, size in entries.items()
        }
        return entries, details

    def recordSourceEntries(self, path, rootPath, entries, details=None):
        self.sourceScanAttempted = True
        relativeBase = path[len(rootPath):].strip('/') if path.startswith(rootPath) else ''
        for name, size in entries.items():
            isDirectory = name.endswith('/')
            cleanName = name[:-1] if isDirectory else name
            relativePath = '/'.join(item for item in (relativeBase, cleanName) if item)
            entry = {
                'path': relativePath,
                'isDir': 1 if isDirectory else 0,
                'size': None if isDirectory else size,
            }
            fingerprint = (details or {}).get(name, {}).get('fingerprint')
            if fingerprint is not None:
                entry['fingerprint'] = fingerprint
            self.sourceSnapshot[relativePath] = entry

    def deleteTargetOnlyDir(self, dstPath, spec, dstRootPath, firstDst):
        """Delete only eligible files below a target-only directory.

        Directory shells are retained so a whole-directory remove cannot bypass
        the active file-size or path exclusion rules.
        """
        if self.breakFlag:
            return
        try:
            dstFiles = self.listDir(dstPath, firstDst, spec, dstRootPath, False)
        except Exception:
            return
        for key, size in dstFiles.items():
            if self.breakFlag:
                return
            if key.endswith('/'):
                self.deleteTargetOnlyDir(dstPath + key, spec, dstRootPath, firstDst)
            elif self.fileSizeAllowed(size):
                self.delFile(dstPath, key, size)

    def syncWithHave(self, srcPath, dstPath, spec, srcRootPath, dstRootPath, firstDst):
        """
        扫描并同步-目标目录存在目录（意味着要继续扫描目标目录）
        :param srcPath: 来源路径，以/结尾
        :param dstPath: 目标路径，以/结尾
        :param spec: 排除项规则
        :param srcRootPath: 来源目录根目录，以/结尾
        :param dstRootPath: 目标目录根目录，以/结尾
        :param firstDst: 是否是第一个目标目录（如果是，将完整扫描源目录，否则使用缓存扫描源目录）
        :return:
        """
        if self.breakFlag:
            return
        try:
            srcFiles = self.listDir(srcPath, firstDst, spec, srcRootPath)
            dstFiles = self.listDir(dstPath, firstDst, spec, dstRootPath, False)
        except Exception:
            # 已在listDir做出日志打印等操作，此处啥都不用做
            return
        for key in srcFiles.keys():
            # 如果是文件
            if not key.endswith('/'):
                if not self.fileSizeAllowed(srcFiles[key]):
                    continue
                # 目标目录没有这个文件或文件大小不匹配(即需要同步)
                if (self.job['method'] == 2
                        or self.sourceFileChangedSinceSnapshot(
                            srcPath, srcRootPath, key
                        )
                        or key not in dstFiles or dstFiles[key] != srcFiles[key]):
                    self.copyFile(srcPath, dstPath, key, srcFiles[key])
            # 如果是目录
            else:
                # 目标目录没有这个目录
                if key not in dstFiles:
                    self.syncWithOutHave(srcPath + key, dstPath + key, spec, srcRootPath, dstRootPath,
                                         firstDst)
                # 目标目录有这个目录，继续递归
                else:
                    self.syncWithHave(srcPath + key, dstPath + key, spec, srcRootPath, dstRootPath,
                                      firstDst)
        if self.job['method'] == 1:
            for dstKey in dstFiles.keys():
                if dstKey not in srcFiles:
                    if dstKey.endswith('/') and self.hasFileSizeFilter():
                        self.deleteTargetOnlyDir(dstPath + dstKey, spec, dstRootPath, firstDst)
                    elif dstKey.endswith('/') or self.fileSizeAllowed(dstFiles[dstKey]):
                        self.delFile(dstPath, dstKey, dstFiles[dstKey])

    def syncWithOutHave(self, srcPath, dstPath, spec, srcRootPath, dstRootPath, firstDst):
        """
        扫描并同步-目标目录为空
        :param srcPath: 来源路径，以/结尾
        :param dstPath: 目标路径，以/结尾
        :param spec:
        :param srcRootPath:
        :param dstRootPath:
        :param firstDst:
        :return:
        """
        if self.breakFlag:
            return
        status = 2
        errMsg = None
        try:
            self.alistClient.mkdir(dstPath, self.job['scanIntervalT'])
        except Exception as e:
            status = 7
            errMsg = str(e)
        # 目录回调
        self.copyHook(srcPath, dstPath, None, None, status=status, errMsg=errMsg, isPath=1)
        if status != 2:
            return
        try:
            srcFiles = self.listDir(srcPath, firstDst, spec, srcRootPath)
        except Exception:
            # 已在listDir做出日志打印等操作，此处啥都不用做
            return
        for key in srcFiles.keys():
            if self.breakFlag:
                break
            if key.endswith('/'):
                self.syncWithOutHave(srcPath + key, dstPath + key, spec, srcRootPath, dstRootPath, firstDst)
            elif self.fileSizeAllowed(srcFiles[key]):
                self.copyFile(srcPath, dstPath, key, srcFiles[key])

    def updateTaskStatus(self):
        """
        所有任务完成后，最终更新任务状态
        """
        self.getCurrent()
        failOrOtherNum = len(self.currentTasks[7]) + len(self.currentTasks[-1])
        status = 7 if self.breakFlag else 2 if failOrOtherNum == 0 else 3
        taskService.updateJobTaskStatus(self.taskId, status, taskList=self.currentTasks, createTime=self.createTime)


class JobClient:
    def __init__(self, job, isInit=False):
        """
        初始化job
        :param job: {id(新增时不需要), enable, srcPath, dstPath, alistId, useCacheT, scanIntervalT, useCacheS, scanIntervalS, method, interval, exclude, cron相关}
        """
        addJobId = 0
        if 'enable' not in job:
            job['enable'] = 1
        if 'method' not in job:
            job['method'] = 0
        if 'id' not in job:
            addJobId = jobMapper.addJob(job)
            job = jobMapper.getJobById(addJobId)
        self.jobId = job['id']
        self.job = job
        self.scheduled = None
        self.scheduledJob = None
        self.jobDoing = False
        self.runLock = threading.Lock()
        # 正在执行中的作业信息；仅在内存中，不入库，高速读写；执行完毕后批量入库，如果遇到异常终止，不会补偿入库
        # 单项结构 {
        #   'taskId':   所属任务id
        #   'alistTaskId': alist任务id
        #   'srcPath':  来源路径
        #   'dstPath':  目标路径
        #   'fileName': 文件名或者文件目录名
        #   'fileSize': 文件大小
        #   'status':   状态 0-等待中，1-运行中，2-成功，3-取消中，4-已取消，5-出错（将重试），
        #               6-失败中，7-已失败，8-等待重试中，9-等待重试回调执行中
        #   'progress': 进度
        #   'errMsg':   失败原因
        # }
        self.currentJobTask = None
        try:
            self.doByTime()
        except Exception as e:
            if isInit or addJobId != 0:
                # 仅在初始化和新增任务时删除错误的任务
                logger = logging.getLogger()
                logger.error(G('del_job_course_error').format(json.dumps(self.job)))
                jobMapper.deleteJob(self.jobId)
            raise e

    def doJob(self, lockAcquired=False):
        """
        执行作业
        :return:
        """
        if not lockAcquired and not self.runLock.acquire(blocking=False):
            return
        self.jobDoing = True
        taskId = None
        try:
            taskId = jobMapper.addJobTask({
                'jobId': self.jobId,
                'runTime': int(time.time())
            })
            if self.job['enable'] == 0:
                raise Exception("abort")
            task = JobTask(taskId, self)
            self.currentJobTask = task
            task.start()
        except Exception as e:
            self.finishRun()
            logger = logging.getLogger()
            errMsg = G('do_job_err').format(str(e))
            logger.error(errMsg)
            if taskId is not None:
                taskService.updateJobTaskStatus(taskId, 6, errMsg)
            logger.exception(e)

    def doManual(self):
        """
        手动执行作业
        :return:
        """
        if not self.runLock.acquire(blocking=False):
            raise Exception(G('job_running'))
        self.jobDoing = True
        doJobThread = threading.Thread(target=self.doJob, kwargs={'lockAcquired': True})
        doJobThread.start()

    def finishRun(self, task=None):
        if task is None or self.currentJobTask is task:
            self.currentJobTask = None
        self.jobDoing = False
        if self.runLock.locked():
            try:
                self.runLock.release()
            except RuntimeError:
                pass

    def doByTime(self):
        params = {
            'func': self.doJob,
            'misfire_grace_time': 15 * 60,
            'trigger': 'interval' if self.job['isCron'] == 0 else 'cron'
        }
        if self.job['isCron'] == 0:
            interval = self.job['interval']
            if interval is not None and str(interval).strip() != '':
                params['minutes'] = interval
            else:
                raise Exception(G('interval_lost'))
        elif self.job['isCron'] == 1:
            flag = 0
            for item in ['year', 'month', 'day', 'week', 'day_of_week', 'hour', 'minute', 'second', 'start_date',
                         'end_date']:
                if item in self.job and self.job[item] is not None and self.job[item] != '':
                    flag += 1
                    params[item] = self.job[item]
            if flag == 0:
                raise Exception(G('cron_lost'))
        else:
            return
        self.scheduled = BackgroundScheduler()
        self.scheduledJob = self.scheduled.add_job(**params)
        self.scheduled.start()
        if self.job['enable'] == 0:
            self.scheduledJob.pause()

    def resumeJob(self):
        """
        恢复作业
        :return:
        """
        if self.scheduledJob is None:
            raise Exception(G('cannot_resume_lost_job'))
        else:
            jobMapper.updateJobEnable(self.jobId, 1)
            self.job['enable'] = 1
            self.scheduledJob.resume()

    def abortJob(self):
        """
        中止作业
        :return:
        """
        if self.currentJobTask:
            self.currentJobTask.breakFlag = True

    def stopJob(self, remove=False):
        """
        停止作业（适用于修改enable）
        :param remove: 是否删除作业，否一般用于禁用作业
        :return:
        """
        self.job['enable'] = 0
        if self.currentJobTask:
            self.currentJobTask.breakFlag = True
        if remove:
            if self.scheduled is not None:
                try:
                    self.scheduled.shutdown(wait=False)
                except Exception as e:
                    logger = logging.getLogger()
                    logger.warning(G('stop_fail').format(str(e)))
                    logger.exception(e)
                self.scheduled = None
        else:
            if self.scheduledJob is not None:
                try:
                    self.scheduledJob.pause()
                except Exception as e:
                    logger = logging.getLogger()
                    logger.warning(G('disable_fail').format(str(e)))
                    logger.exception(e)
        if not remove:
            jobMapper.updateJobEnable(self.jobId, 0)
            jobMapper.updateJobTaskStatusByStatusAndJobId(self.jobId)
