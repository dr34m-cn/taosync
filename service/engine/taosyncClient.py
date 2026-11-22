import posixpath
import threading
import time
import uuid
from copy import copy
from contextlib import nullcontext
from collections import OrderedDict

from common.intervalGate import IntervalGate
from mapper import storageMapper
from service.alist.alistClient import checkExs
from service.storage import storageService
from service.storage.drivers.base import (
    RAPID_UPLOAD,
    TransferCancelled,
    check_cancel,
    child_path,
    normalize_path,
    stream_transfer,
)
from service.storage.factory import createDriver
from service.storage.localAccess import LocalPathError
from service.storage.pathIdentity import mount_paths_overlap, virtual_paths_overlap
from service.storage.localAccess import sync_listing
from common.fileFingerprint import contentHashes
from service.storage.drivers.aliyun import AliyunDriveDriver
from service.storage.drivers.crypt import CryptDriver
from service.storage.backupCipher import BackupNamespaceError
from service.storage.mountConfig import getMountEncryptionKey
from service.storage.drivers.scanState import ScanState


_mount_refresh_locks = {}
_mount_refresh_locks_guard = threading.Lock()


def _get_mount_refresh_lock(mount_id, auth_version):
    key = (int(mount_id), int(auth_version))
    with _mount_refresh_locks_guard:
        return _mount_refresh_locks.setdefault(key, threading.Lock())


class _CopyTask:
    def __init__(self, client, source_path, destination_path, delete_source=False):
        self.client = client
        self.id = uuid.uuid4().hex
        self.source_path = source_path
        self.destination_path = destination_path
        self.delete_source = delete_source
        self.state = 0
        self.progress = 0.0
        self.rapid_upload = False
        self.error = ""
        self.cancel_event = threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.delete_when_done = False
        self.finished = threading.Event()

    def start(self):
        self.thread = threading.Thread(target=self._run, name="taosync-copy-" + self.id[:8], daemon=True)
        self.thread.start()

    def _report(self, value):
        # Publish the final progress together with the transfer method in _succeed.
        if value >= 1:
            return
        with self.lock:
            self.progress = round(max(0.0, min(1.0, float(value))) * 100, 2)

    def _succeed(self, result=None):
        with self.lock:
            self.rapid_upload = result == RAPID_UPLOAD
            self.progress = 100.0
            self.state = 2

    def _run(self):
        with self.lock:
            self.state = 1
        try:
            source_mount, source_relative = self.client.resolve(self.source_path)
            destination_mount, destination_relative = self.client.resolve(self.destination_path)
            source_driver = self.client.getDriver(source_mount)
            destination_driver = self.client.getDriver(destination_mount)
            native_move = getattr(source_driver, "can_move_to", None)
            if self.delete_source and callable(native_move) and native_move(destination_driver):
                source_driver.move_to(source_relative, destination_driver, destination_relative,
                                      self._report, self.cancel_event)
                self.client._invalidateScanPath(source_mount, source_relative)
                self.client._invalidateScanPath(destination_mount, destination_relative)
                self.client._invalidateMountCache(source_mount["id"])
                self.client._invalidateMountCache(destination_mount["id"])
                self._succeed()
                return
            metadata = self.client.fileMetadata(source_mount, source_relative)
            size = int(metadata.get("size") or 0)
            if self.source_path == self.destination_path:
                self._succeed()
                return
            if source_mount["id"] == destination_mount["id"]:
                with self.client._scanScope(destination_mount):
                    result = source_driver.copy(
                        source_relative,
                        destination_relative,
                        size=size,
                        progress=self._report,
                        cancel=self.cancel_event,
                        metadata=metadata,
                    )
                if destination_mount['driverType'] != 'crypt':
                    self.client._invalidateScanPath(destination_mount, destination_relative)
            else:
                with self.client._scanScope(destination_mount):
                    result = stream_transfer(
                        source_driver,
                        source_relative,
                        destination_driver,
                        destination_relative,
                        size,
                        self._report,
                        self.cancel_event,
                        metadata,
                    )
                self.client._rememberHash(source_mount, source_relative, metadata)
            self.client._invalidateMountCache(destination_mount["id"])
            if self.delete_source:
                # The destination commit is complete. A late cancellation
                # must not relabel it or remove its source.
                if self.cancel_event.is_set():
                    self._succeed(result)
                    return
                source_driver.delete(source_relative)
                self.client._invalidateScanPath(source_mount, source_relative)
                self.client._invalidateMountCache(source_mount["id"])
            self._succeed(result)
        except TransferCancelled:
            with self.lock:
                self.state = 4
                self.error = "transfer cancelled"
        except Exception as exc:
            with self.lock:
                self.state = 7
                self.error = exc.args if isinstance(exc, (LocalPathError, BackupNamespaceError)) else str(exc)
        finally:
            with self.lock:
                delete_when_done = self.delete_when_done
            self.finished.set()
            if delete_when_done:
                self.client._forgetTask(self.id, self)

    def info(self):
        with self.lock:
            return {
                "id": self.id,
                "name": "copy {} to {}".format(self.source_path, self.destination_path),
                "state": self.state,
                "status": "running" if self.state == 1 else "finished",
                "progress": self.progress,
                "rapidUpload": self.rapid_upload,
                "error": str(LocalPathError(*self.error)) if isinstance(self.error, tuple) else self.error,
                **({"localError": self.error} if isinstance(self.error, tuple) else {}),
            }

    def cancel(self):
        self.cancel_event.set()

    def deleteAfterFinish(self):
        with self.lock:
            self.delete_when_done = True
            terminal = self.state in (2, 4, 7)
        if terminal:
            self.client._forgetTask(self.id, self)


class TaoSyncClient:
    """AList-compatible facade over TaoSync's internal storage drivers."""

    def __init__(self, engineId):
        self.alistId = int(engineId)
        self.user = "TaoSync"
        self.waitGate = IntervalGate()
        self.tasks = {}
        self.tasks_lock = threading.Lock()
        self.mounts = {}
        self.entry_cache = {}
        self.entry_cache_lock = threading.Lock()
        self.cache_ttl = 15.0
        self.hash_cache = OrderedDict()
        self.hash_cache_lock = threading.Lock()
        rows = storageMapper.getMountList(self.alistId)
        by_id = {}
        self.related_mounts = {}
        # Load the physical drivers first. A filter shares its backing driver's
        # credentials, connections and locks regardless of database row order.
        for row in sorted(rows, key=lambda row: row['driverType'] == 'crypt'):
            mount_id = int(row["id"])
            auth_version = int(row.get("authVersion") or 1)

            def save_config(
                config,
                expected_tokens=None,
                current_id=mount_id,
                current_auth_version=auth_version,
            ):
                return storageService.updateMountConfig(
                    current_id,
                    current_auth_version,
                    config,
                    expectedTokens=expected_tokens,
                )

            def load_config(current_id=mount_id):
                return storageMapper.getMountById(current_id)

            row = dict(row)
            try:
                config = row['config']
                if row['driverType'] == 'crypt':
                    target = by_id.get(config['target_mount_id'])
                    if target is None or target['driverType'] == 'crypt':
                        raise ValueError('encryption target directory is unavailable')
                    row['driver'] = CryptDriver(self.getDriver(target), config['target_path'],
                                                getMountEncryptionKey(config), config['encrypt_dir_names'],
                                                namespace_id=(self.alistId, target['id']))
                    self.related_mounts.setdefault(target['id'], {target['id']}).add(mount_id)
                else:
                    row['driver'] = createDriver(
                        row['driverType'], config, save_config=save_config, load_config=load_config,
                        refresh_lock=_get_mount_refresh_lock(mount_id, auth_version), auth_version=auth_version,
                    )
                row["driverError"] = ""
            except Exception as exc:
                # Keep a bad/offline mount visible and repairable without
                # preventing healthy mounts from being used.
                row["driver"] = None
                row["driverError"] = exc.args if isinstance(exc, LocalPathError) else str(exc)
            self.mounts[row["name"]] = row
            by_id[mount_id] = row
        self.related_mounts = {mount_id: group for group in self.related_mounts.values() for mount_id in group}

    def updateAlistId(self, alistId):
        self.alistId = int(alistId)

    def forSync(self):
        # Keep credentials, connections, task registry and driver locks shared,
        # while scan identities and entry caches belong to this run alone.
        client = copy(self)
        client.scan_states = {mount['id']: ScanState() for mount in self.mounts.values()
                              if isinstance(mount.get('driver'), AliyunDriveDriver)}
        client.entry_cache = {}
        client.entry_cache_lock = threading.Lock()
        client.cache_owner = self
        return client

    def _scanScope(self, mount):
        if mount['driverType'] == 'crypt':
            backing = self.getDriver(mount).backing
            state = getattr(self, 'scan_states', {}).get(mount['config']['target_mount_id'])
            if state is not None:
                return backing.scan_scope(state)
            return nullcontext()
        state = getattr(self, 'scan_states', {}).get(mount['id'])
        if state is not None:
            return self.getDriver(mount).scan_scope(state)
        return nullcontext()

    def _invalidateScanPath(self, mount, path):
        if mount['driverType'] == 'crypt':
            config = mount['config']
            state = getattr(self, 'scan_states', {}).get(config['target_mount_id'])
            if state is not None:
                state.invalidate(config['target_path'])
            return
        state = getattr(self, 'scan_states', {}).get(mount['id'])
        if state is not None:
            state.invalidate(posixpath.dirname(path) or '/')

    def mountPathsOverlap(self, firstPath, secondPath):
        return mount_paths_overlap(self.mounts, firstPath, secondPath)

    def pathsOverlap(self, firstPath, secondPath):
        return (
            virtual_paths_overlap(firstPath, secondPath, case_sensitive=True)
            or self.mountPathsOverlap(firstPath, secondPath)
        )

    def checkWait(self, path, scanInterval=0):
        if not scanInterval:
            return
        normalized = normalize_path(path)
        root = normalized.strip("/").split("/", 1)[0] if normalized != "/" else "/"
        self.waitGate.wait(root, scanInterval)

    def resolve(self, path):
        normalized = normalize_path(path, allow_root=False)
        parts = normalized.strip("/").split("/")
        mount = self.mounts.get(parts[0])
        if mount is None:
            raise FileNotFoundError("storage directory not found: " + parts[0])
        relative = "/" + "/".join(parts[1:]) if len(parts) > 1 else "/"
        return mount, relative

    @staticmethod
    def getDriver(mount):
        driver = mount.get("driver")
        if driver is None:
            detail = mount.get("driverError") or "driver could not be initialized"
            if isinstance(detail, tuple):
                raise LocalPathError(*detail)
            raise RuntimeError(
                "storage directory '{}' is unavailable: {}".format(
                    mount.get("name", ""), detail
                )
            )
        return driver

    def _invalidateMountCache(self, mount_id=None):
        with self.entry_cache_lock:
            if mount_id is None:
                self.entry_cache.clear()
            else:
                related = self.related_mounts.get(mount_id, {mount_id})
                for key in [key for key in self.entry_cache if key[0] in related]:
                    self.entry_cache.pop(key, None)
        owner = getattr(self, 'cache_owner', None)
        if owner is not None:
            owner._invalidateMountCache(mount_id)

    def _entries(self, path, useCache=0):
        normalized = normalize_path(path)
        if normalized == "/":
            return [{"name": name, "is_dir": True, "size": None} for name in sorted(self.mounts)]
        mount, relative = self.resolve(normalized)
        cache_key = (mount["id"], relative)
        if int(useCache or 0) == 1:
            with self.entry_cache_lock:
                cached = self.entry_cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < self.cache_ttl:
                return [dict(item) for item in cached[1]]
        try:
            with self._scanScope(mount):
                token = sync_listing.set(hasattr(self, 'cache_owner'))
                try:
                    entries = self.getDriver(mount).list(relative, details=True)
                finally:
                    sync_listing.reset(token)
        except FileNotFoundError:
            raise FileNotFoundError("directory not found: " + normalized)
        with self.entry_cache_lock:
            self.entry_cache[cache_key] = (time.monotonic(), [dict(item) for item in entries])
        return entries

    def fileListApi(self, path, useCache=0, scanInterval=0, spec=None, rootPath=None):
        details = self.fileListDetailApi(
            path, useCache, scanInterval, spec, rootPath
        )
        return {
            name: {} if detail['isDir'] else detail['size']
            for name, detail in details.items()
        }

    def fileDetail(self, directory, name):
        mount, relative = self.resolve(child_path(directory, name))
        try:
            item = self.getDriver(mount).file_metadata(relative)
        except (FileNotFoundError, IsADirectoryError):
            return None
        return {'isDir': 0, 'size': item['size'], 'fingerprint': item.get('fingerprint'),
                'contentHashes': contentHashes(item) if mount.get('driverType') == 'aliyun' else {}}

    def fileListDetailApi(self, path, useCache=0, scanInterval=0, spec=None, rootPath=None):
        """Return driver metadata without changing fileListApi's legacy shape."""
        self.checkWait(path, scanInterval)
        entries = self._entries(path, useCache)
        cloudHashes = bool(path.strip('/')) and self.resolve(path)[0].get('driverType') == 'aliyun'
        result = {
            item["name"] + "/" if item["is_dir"] else item["name"]: {
                "isDir": 1 if item["is_dir"] else 0,
                "size": None if item["is_dir"] else int(item.get("size") or 0),
                "fingerprint": item.get("fingerprint"),
                **({"contentHashes": item["contentHashes"]} if cloudHashes and item.get("contentHashes") else {}),
                **{key: item[key] for key in ("sha1", "created_at", "modified_at") if item.get(key) is not None},
            }
            for item in entries
        }
        if spec and result:
            rootPath = rootPath or path
            current = normalize_path(path)
            root = normalize_path(rootPath)
            if current == root:
                relative = ""
            elif current.startswith(root.rstrip("/") + "/"):
                relative = current[len(root.rstrip("/")) + 1:] + "/"
            else:
                relative = current.lstrip("/") + "/"
            result = checkExs(relative, result, spec)
        return result

    def filePathList(self, path):
        return [{"path": item["name"]} for item in self._entries(path, 0) if item["is_dir"]]

    def allFileList(self, path, useCache=0, scanInterval=0, spec=None, rootPath=None):
        rootPath = rootPath or path
        result = self.fileListApi(path, useCache, scanInterval, spec, rootPath)
        for name in list(result.keys()):
            if name.endswith("/"):
                result[name] = self.allFileList(
                    normalize_path(path).rstrip("/") + "/" + name,
                    useCache,
                    scanInterval,
                    spec,
                    rootPath,
                )
        return result

    def mkdir(self, path, scanInterval=0):
        self.checkWait(path, scanInterval)
        normalized = normalize_path(path)
        mount, relative = self.resolve(normalized)
        if relative != "/":
            with self._scanScope(mount):
                self.getDriver(mount).mkdir(relative)
            self._invalidateMountCache(mount["id"])

    def deleteFile(self, path, names, scanInterval=0):
        self.checkWait(path, scanInterval)
        for name in names:
            full_path = child_path(path, name)
            mount, relative = self.resolve(full_path)
            if relative == "/":
                raise ValueError("a mounted storage root cannot be deleted by a job")
            try:
                with self._scanScope(mount):
                    self.getDriver(mount).delete(relative)
            except FileNotFoundError:
                # Source-snapshot retries may repeat a delete that already
                # succeeded for another target before a later operation failed.
                pass
            self._invalidateMountCache(mount["id"])

    def fileSize(self, mount, relative):
        return int(self.fileMetadata(mount, relative).get("size") or 0)

    def fileMetadata(self, mount, relative):
        metadata = self.getDriver(mount).file_metadata(relative)
        key = self._hashKey(mount, relative, metadata)
        with self.hash_cache_lock:
            cached = self.hash_cache.get(key) if key is not None else None
            if cached and time.monotonic() - cached[0] < 600:
                if not metadata.get("sha1"):
                    metadata["sha1"] = cached[1]
                self.hash_cache.move_to_end(key)
        return metadata

    @staticmethod
    def _hashKey(mount, relative, metadata):
        fingerprint = metadata.get("fingerprint")
        return (mount["id"], relative, metadata.get("size"), fingerprint) if fingerprint else None

    def _rememberHash(self, mount, relative, metadata):
        key = self._hashKey(mount, relative, metadata)
        if key is None or not metadata.get("sha1"):
            return
        with self.hash_cache_lock:
            self.hash_cache[key] = (time.monotonic(), metadata["sha1"])
            self.hash_cache.move_to_end(key)
            while len(self.hash_cache) > 512:
                self.hash_cache.popitem(last=False)

    def copyFile(self, srcDir, dstDir, name):
        return self._startCopyTask(srcDir, dstDir, name, delete_source=False)

    def _startCopyTask(self, srcDir, dstDir, name, delete_source):
        source = child_path(srcDir, name)
        destination = child_path(dstDir, name)
        task = _CopyTask(self, source, destination, delete_source=delete_source)
        with self.tasks_lock:
            self.tasks[task.id] = task
        task.start()
        return task.id

    def moveFile(self, srcDir, dstDir, name):
        return self._startCopyTask(srcDir, dstDir, name, delete_source=True)

    def relocateFile(self, source, destination):
        source = normalize_path(source, allow_root=False)
        destination = normalize_path(destination, allow_root=False)
        for path in (source, destination):
            mount, relative = self.resolve(path)
            if relative == "/" or not getattr(self.getDriver(mount), "supports_native_move", False):
                raise ValueError("cloud operations require a path below an Aliyun storage root")
        source_mount, _ = self.resolve(source)
        destination_mount, _ = self.resolve(destination)
        if not self.getDriver(source_mount).can_move_to(self.getDriver(destination_mount)):
            raise ValueError("cloud moves require the same Aliyun drive")
        task = _CopyTask(self, source, destination, delete_source=True)
        with self.tasks_lock:
            self.tasks[task.id] = task
        task.start()
        return task.id

    def renameFile(self, path, name):
        return self.relocateFile(path, child_path(posixpath.dirname(normalize_path(path)), name))

    def _forgetTask(self, taskId, expected=None):
        with self.tasks_lock:
            current = self.tasks.get(str(taskId))
            if expected is None or current is expected:
                self.tasks.pop(str(taskId), None)

    def _task(self, taskId):
        with self.tasks_lock:
            task = self.tasks.get(str(taskId))
        if task is None:
            raise FileNotFoundError("404 internal copy task not found")
        return task

    def taskInfo(self, taskId):
        return self._task(taskId).info()

    def waitTask(self, taskId, timeout):
        """Block until the copy task finishes or the timeout elapses."""
        with self.tasks_lock:
            task = self.tasks.get(str(taskId))
        if task is not None:
            task.finished.wait(timeout)

    def copyTaskDone(self):
        with self.tasks_lock:
            tasks = list(self.tasks.values())
        return [task.info() for task in tasks if task.info()["state"] in (2, 4, 7)]

    def copyTaskUnDone(self):
        with self.tasks_lock:
            tasks = list(self.tasks.values())
        return [task.info() for task in tasks if task.info()["state"] not in (2, 4, 7)]

    def copyTaskRetry(self, taskId):
        old = self._task(taskId)
        if old.info()["state"] not in (4, 7):
            raise ValueError("only failed or cancelled tasks can be retried")
        task = _CopyTask(self, old.source_path, old.destination_path, old.delete_source)
        task.id = old.id
        with self.tasks_lock:
            self.tasks[task.id] = task
        task.start()

    def copyTaskClearSucceeded(self):
        with self.tasks_lock:
            for taskId in [key for key, task in self.tasks.items() if task.info()["state"] == 2]:
                del self.tasks[taskId]

    def copyTaskDelete(self, taskId):
        task = self._task(taskId)
        if task.info()["state"] not in (2, 4, 7):
            task.cancel()
            task.deleteAfterFinish()
            return
        self._forgetTask(taskId)

    def copyTaskCancel(self, taskId):
        self._task(taskId).cancel()
