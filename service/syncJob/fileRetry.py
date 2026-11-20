import posixpath

from pathspec import PathSpec
from pathspec.patterns.gitwildmatch import GitWildMatchPattern

from service.syncJob.jobClient import JobTask, virtualPathsOverlap


class FileRetryTask(JobTask):
    """A normal queued run with a single-file producer instead of a tree scan."""

    triggersLinks = False

    def __init__(self, taskId, client, item):
        super().__init__(taskId, client)
        self.item = item

    def commitSourceSnapshot(self):
        # A single-file view must never replace the job's complete snapshot.
        pass

    def removeMovedDirectories(self, movedPaths):
        # The retry is authorized for one file, not its parent directories.
        pass

    def sync(self):
        try:
            self.retryFile()
        except Exception as exc:
            self.fatalError = str(exc)
            item = self.item
            self.copyHook(item['srcPath'], item['dstPath'], item['fileName'], item['fileSize'],
                          status=7, errMsg=str(exc), copyType=item['type'])
        finally:
            self.scanFinish = True
            self._wake()

    def retryFile(self):
        item = self.item
        name, operation = item['fileName'], item['type']
        srcRoot = self.normalizeRoot(self.job['srcPath'])
        dstRoots = [self.normalizeRoot(root) for root in self.job['dstPath'].split(':')]
        overlaps = getattr(self.alistClient, 'pathsOverlap', virtualPathsOverlap)
        if any(overlaps(srcRoot, root) for root in dstRoots):
            raise ValueError('来源与目标目录重叠')
        if not name or name in ('.', '..') or '/' in name or '\\' in name:
            raise ValueError('无效的文件名')

        if operation == 1:
            matches = [root for root in dstRoots if (item['dstPath'] or '').startswith(root)]
            if self.job['method'] != 1 or len(matches) != 1:
                raise ValueError('当前作业配置不允许重试此删除操作')
            relative = item['dstPath'][len(matches[0]):] + name
        else:
            if not (item['srcPath'] or '').startswith(srcRoot) or operation != (2 if self.job['method'] == 2 else 0):
                raise ValueError('文件不属于当前作业的来源或同步方式已变更')
            relative = item['srcPath'][len(srcRoot):] + name
        parts = relative.split('/')
        if any(part in ('', '.', '..') or '\\' in part for part in parts):
            raise ValueError('无效的文件路径')
        if self.job.get('exclude'):
            spec = PathSpec.from_lines(GitWildMatchPattern, self.job['exclude'].split(':'))
            if any(spec.match_file('/'.join(parts[:i]) + '/') for i in range(1, len(parts))) or spec.match_file(relative):
                raise ValueError('文件已被当前作业排除')
        destinations = [self.entryLocation(root, relative)[0] for root in dstRoots]
        if item['dstPath'] not in destinations and not (operation == 2 and item['dstPath'] is None):
            raise ValueError('文件不属于当前作业的目标目录')
        if operation == 1:
            self.retryDelete(srcRoot, parts)
            return

        src = item['srcPath']
        _, details = self.readDirectory(src, 0, 0)
        entry = details.get(name)
        if not entry or entry['isDir'] or not self.fileSizeAllowed(entry['size']):
            raise ValueError('源文件不存在或不符合当前大小限制')
        self.sourceSnapshot[relative] = dict(entry, path=relative)
        self.sourceScanAttempted = True
        # Move cleanup requires delivery of this version to EVERY target, not
        # a size match against successful deliveries from a historical run.
        for dst in destinations if operation == 2 else [item['dstPath']]:
            self.copyFile(src, dst, name, entry['size'])

    def retryDelete(self, srcRoot, parts):
        name, dst = parts[-1], self.item['dstPath']
        directory = srcRoot
        for index, part in enumerate(parts):
            files, _ = self.readDirectory(directory, 0, 0)
            if index == 0 and not files:
                raise ValueError('源目录为空，已阻止删除目标文件')
            if part + '/' in files and index < len(parts) - 1:
                directory = posixpath.join(directory, part) + '/'
                continue
            if any(key.rstrip('/').casefold() == part.casefold() for key in files):
                raise ValueError('来源路径已存在同名项，已阻止删除')
            break
        files, _ = self.readDirectory(dst, 0, 0)
        if name not in files:
            if name + '/' in files:
                raise ValueError('目标已变为目录，已阻止删除')
            self.delHook(dst, name, self.item['fileSize'])  # already gone
        elif files[name] != self.item['fileSize'] or not self.fileSizeAllowed(files[name]):
            raise ValueError('目标文件大小已变化或不符合当前大小限制')
        else:
            self.delFile(dst, name, files[name])

    def retryProgress(self):
        state = self.getCurrent()
        count = sum(state['num'].values())
        done = state['num']['success'] * 100
        progress = done + sum(float(row.get('progress') or 0) for row in state['doingTask'])
        return {'queued': not self.firstSync and not self.scanFinish or state['num']['wait'] == count,
                'progress': min(100, progress / count) if count else 0}
