import logging
import posixpath
import threading
from collections import deque

from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

from common.fileRetryReason import FileRetryError
from mapper import jobMapper
from service.syncJob.jobClient import JobTask, validateJobPaths, virtualPathsOverlap


class FileRetryTask(JobTask):
    """One appendable run per job, with independent outcomes for its source rows."""

    triggersLinks = False
    notify = False

    def __init__(self, taskId, client, admissionLock):
        super().__init__(taskId, client)
        self.job = dict(self.job, scanIntervalT=0)
        self.admissionLock = admissionLock
        self.pending = deque()
        self.item = None
        self.moved = set()

    def enqueue(self, items):
        with self.stateLock:
            self.pending.extend(items)

    def start(self):
        self.submitThread.start()

    def getCurrent(self):
        with self.stateLock:
            state = super().getCurrent()
            queued = [dict(item, status=0, progress=0) for item in self.pending]
            self.currentTasks[0].extend(queued)
            state['num']['wait'] += len(queued)
            state['size']['wait'] += sum((item['fileSize'] or 0) for item in queued if item['type'] != 1)
        state.update(fileRetry=True, scanFinish=True)
        return state

    def taskSubmit(self):
        try:
            while True:
                # Admission and the empty-queue transition must agree on who owns the run.
                with self.admissionLock:
                    if self.breakFlag or not self.pending:
                        if not self._jobRemoved():
                            self.updateTaskStatus()
                        self.jobClient.finishRun(self)
                        return
                    with self.stateLock:
                        self.item = self.pending.popleft()
                        self.itemStart = len(self.finish)
                self.runItem()
        except Exception as exc:
            logging.getLogger().exception(exc)
            with self.admissionLock:
                try:
                    if not self._jobRemoved():
                        jobMapper.updateJobTaskStatus(self.taskId, 6, str(exc))
                finally:
                    self.jobClient.finishRun(self)
        finally:
            if self._jobRemoved():
                jobMapper.deleteJobTaskByTaskId(self.taskId)

    def runItem(self):
        self.scanFinish = False
        self.sourceSnapshot.clear()
        self.deliveredSourceFiles.clear()
        self.itemError = None
        self.syncThread = threading.Thread(target=self.sync)
        self.syncThread.start()
        self.runTransfers()
        if self._jobRemoved():
            return
        records = self.finish[self.itemStart:]
        if self.job['method'] == 2 and not self.breakFlag:
            self.finalizeMove(records)
            records = self.finish[self.itemStart:]
        failure = next((row for row in records if row['status'] != 2), None)
        status = 7 if self.breakFlag else 6 if self.itemError else 3 if failure else 2
        if self.timedOut:
            status = 5
        error = self.itemError or (failure and failure['errMsg'])
        if records:
            jobMapper.addJobTaskItemMany(records)
        if status == 2 and self.item['type'] == 2:
            self.moved.add(self.moveKey())
        jobMapper.saveFileRetryResult(self.taskId, self.item['id'], status, error)
        # Preserve a task-level reason for a wholly failed run.
        if self.itemStart == 0:
            self.fatalError = self.itemError
        elif self.itemError is None:
            self.fatalError = None

    def moveKey(self):
        return self.item['taskId'], self.item['srcPath'], self.item['fileName']

    def removeMovedDirectories(self, movedPaths):
        # The retry is authorized for one file, not its parent directories.
        pass

    def sync(self):
        try:
            self.retryFile()
        except Exception as exc:
            self.itemError = exc if isinstance(exc, FileRetryError) else str(exc)
            item = self.item
            self.copyHook(item['srcPath'], item['dstPath'], item['fileName'], item['fileSize'],
                          status=7, errMsg=self.itemError, copyType=item['type'])
        finally:
            self.scanFinish = True
            self._wake()

    def retryFile(self):
        item = self.item
        name, operation = item['fileName'], item['type']
        srcRoot = self.normalizeRoot(self.job['srcPath'])
        dstRoots = [self.normalizeRoot(root) for root in self.job['dstPath'].split(':')]
        overlaps = getattr(self.alistClient, 'pathsOverlap', virtualPathsOverlap)
        validateJobPaths(srcRoot, dstRoots, overlaps)
        if not name or name in ('.', '..') or '/' in name or '\\' in name:
            raise FileRetryError('file_retry_invalid_name')

        if operation == 1:
            matches = [root for root in dstRoots if (item['dstPath'] or '').startswith(root)]
            if self.job['method'] != 1 or len(matches) != 1:
                raise FileRetryError('file_retry_delete_not_allowed')
            relative = item['dstPath'][len(matches[0]):] + name
        else:
            if not (item['srcPath'] or '').startswith(srcRoot) or operation != (2 if self.job['method'] == 2 else 0):
                raise FileRetryError('file_retry_source_or_method_changed')
            relative = item['srcPath'][len(srcRoot):] + name
        parts = relative.split('/')
        if any(part in ('', '.', '..') or '\\' in part for part in parts):
            raise FileRetryError('file_retry_invalid_path')
        spec = None
        if self.job.get('exclude'):
            spec = PathSpec.from_lines(GitWildMatchPattern, self.job['exclude'].split(':'))
            if any(spec.match_file('/'.join(parts[:i]) + '/') for i in range(1, len(parts))) or spec.match_file(relative):
                raise FileRetryError('file_retry_excluded')
        destinations = [self.entryLocation(root, relative)[0] for root in dstRoots]
        if item['dstPath'] not in destinations and not (operation == 2 and item['dstPath'] is None):
            raise FileRetryError('file_retry_wrong_destination')
        if operation == 1:
            self.retryDelete(srcRoot, parts, spec)
            return

        # One successful move already delivered this source version to every target.
        if operation == 2 and self.moveKey() in self.moved:
            return
        src = item['srcPath']
        if operation == 2:
            # A move must verify the exact source name and version before deletion.
            _, details = self.readDirectory(src, 0, 0)
            entry = details.get(name)
        else:
            entry = self.alistClient.fileDetail(src, name)
        if not entry or entry['isDir'] or not self.fileSizeAllowed(entry['size']):
            raise FileRetryError('file_retry_source_missing_or_size')
        self.sourceSnapshot[relative] = dict(entry, path=relative)
        self.sourceScanAttempted = True
        # Move cleanup requires delivery of this version to EVERY target, not
        # a size match against successful deliveries from a historical run.
        for dst in destinations if operation == 2 else [item['dstPath']]:
            self.copyFile(src, dst, name, entry['size'])

    def retryDelete(self, srcRoot, parts, spec):
        name, dst = parts[-1], self.item['dstPath']
        directory = srcRoot
        for index, part in enumerate(parts):
            files, _ = self.readDirectory(directory, 0, 0)
            # Match the full-sync empty-root guard, but keep raw names for conflict checks below.
            if index == 0 and not any(spec is None or not spec.match_file(key) for key in files):
                raise FileRetryError('source_empty_protect', srcRoot, dst)
            if part + '/' in files and index < len(parts) - 1:
                directory = posixpath.join(directory, part) + '/'
                continue
            if any(key.rstrip('/').casefold() == part.casefold() for key in files):
                raise FileRetryError('file_retry_source_conflict')
            break
        files, _ = self.readDirectory(dst, 0, 0)
        if name not in files:
            if name + '/' in files:
                raise FileRetryError('file_retry_target_directory')
            self.delHook(dst, name, self.item['fileSize'])  # already gone
        elif files[name] != self.item['fileSize'] or not self.fileSizeAllowed(files[name]):
            raise FileRetryError('file_retry_target_size_changed')
        else:
            self.delFile(dst, name, files[name])

    def retryProgress(self, itemId):
        with self.stateLock:
            if not self.item or self.item['id'] != itemId:
                return {'queued': True, 'progress': 0}
            active = list(self.doing.values())
            finished = self.finish[self.itemStart:]
            total = len(active) + len(finished) + len(self.waiting)
            progress = sum(float(item.progress or 0) for item in active)
            progress += 100 * sum(row['status'] == 2 for row in finished)
            return {'queued': False, 'progress': min(100, progress / total) if total else 0}
