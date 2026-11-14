import ntpath
import stat
import threading
import uuid
from contextlib import contextmanager
from functools import wraps

from common.fileFingerprint import fileFingerprint

from .base import StorageDriver, check_cancel, normalize_path


def _smb_operation(operation):
    @wraps(operation)
    def wrapped(self, *args, **kwargs):
        with self._connection():
            return operation(self, *args, **kwargs)

    return wrapped


class SmbDriver(StorageDriver):
    driver_type = "smb"
    _MAX_IDLE_CONNECTIONS = 4

    def __init__(self, config):
        self.server = str(config.get("host") or config.get("server") or "").strip()
        self.share = str(config.get("share") or "").strip().strip("\\/")
        if not self.server or not self.share:
            raise ValueError("SMB host and share are required")
        if any(char in self.server for char in "\\/\x00") or any(
            part in (".", "..") for part in self.share.replace("/", "\\").split("\\")
        ) or "\\" in self.share or "/" in self.share:
            raise ValueError("invalid SMB host or share")
        self.port = int(config.get("port") or 445)
        username = str(config.get("username") or "")
        domain = str(config.get("domain") or "").strip()
        self.username = f"{domain}\\{username}" if domain and username and "\\" not in username else username
        self.password = str(config.get("password") or "")
        root = str(config.get("root_path") or "").replace("/", "\\").strip("\\")
        if any(part in (".", "..") for part in root.split("\\") if part):
            raise ValueError("SMB root_path cannot contain dot segments")
        self.root = "\\\\{}\\{}".format(self.server, self.share)
        if root:
            self.root += "\\" + root
        # A credit window belongs to a connection. Lease it to one operation
        # so scans and transfers cannot exhaust each other's credits.
        self._connection_local = threading.local()
        self._pool_lock = threading.Lock()
        self._idle_connections = []
        self._pool_generation = 0

    @contextmanager
    def _connection(self):
        if getattr(self._connection_local, "cache", None) is not None:
            yield
            return
        with self._pool_lock:
            cache = self._idle_connections.pop() if self._idle_connections else {}
            generation = self._pool_generation
        self._connection_local.cache = cache
        reusable = False
        try:
            yield
            reusable = True
        finally:
            del self._connection_local.cache
            with self._pool_lock:
                if (
                    reusable
                    and generation == self._pool_generation
                    and len(self._idle_connections) < self._MAX_IDLE_CONNECTIONS
                ):
                    self._idle_connections.append(cache)
                    cache = None
            if cache is not None:
                self._close_cache(cache)

    @staticmethod
    def _close_cache(cache):
        for connection in list(cache.values()):
            try:
                # Logoff is another credit-consuming request and may fail on
                # the exhausted connection we are trying to dispose of.
                connection.disconnect(close=False)
            except Exception:
                pass
        cache.clear()

    def _connection_kwargs(self):
        kwargs = {"port": self.port, "connection_cache": self._connection_local.cache}
        if self.username:
            kwargs["username"] = self.username
            kwargs["password"] = self.password
        return kwargs

    def _client(self):
        try:
            import smbclient
        except ImportError as exc:
            raise RuntimeError("SMB support requires the smbprotocol package") from exc
        session = smbclient.register_session(self.server, **self._connection_kwargs())
        connection = session.connection
        with connection.sequence_lock:
            available = connection.sequence_window["high"] - connection.sequence_window["low"]
        if available == 0:
            self._close_cache(self._connection_local.cache)
            session = smbclient.register_session(self.server, **self._connection_kwargs())
            connection = session.connection
            with connection.sequence_lock:
                available = connection.sequence_window["high"] - connection.sequence_window["low"]
        if 0 < available < 3:
            # smbclient.stat() compounds CREATE, QUERY_INFO and CLOSE.
            connection.echo(sid=session.session_id, credit_request=64)
        return smbclient

    def close(self):
        with self._pool_lock:
            caches = self._idle_connections
            self._idle_connections = []
            self._pool_generation += 1
        for cache in caches:
            self._close_cache(cache)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _remote(self, path, allow_root=True):
        path = normalize_path(path, allow_root=allow_root)
        relative = path.lstrip("/").replace("/", "\\")
        remote = ntpath.normpath(ntpath.join(self.root, relative))
        root_lower = self.root.rstrip("\\").casefold()
        remote_lower = remote.casefold()
        if remote_lower != root_lower and not remote_lower.startswith(root_lower + "\\"):
            raise ValueError("path escapes SMB root")
        return remote

    @staticmethod
    def _entry_is_reparse(entry):
        attributes = getattr(getattr(entry, "smb_info", None), "file_attributes", 0)
        return bool(attributes & 0x400) or bool(
            getattr(entry, "is_symlink", lambda: False)()
        )

    def _assert_no_reparse(self, client, remote, allow_missing=False):
        """Reject SMB symbolic links/junctions before following them."""
        kwargs = self._connection_kwargs()
        root = self.root.rstrip("\\")
        relative = remote[len(root):].strip("\\")
        current = root
        for part in relative.split("\\") if relative else []:
            current = current + "\\" + part
            try:
                info = client.stat(current, follow_symlinks=False, **kwargs)
            except FileNotFoundError:
                if allow_missing:
                    return
                raise
            if getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("SMB symbolic links and reparse points are not supported")

    @_smb_operation
    def list(self, path, details=False):
        client = self._client()
        remote = self._remote(path)
        self._assert_no_reparse(client, remote)
        result = []
        with client.scandir(remote, **self._connection_kwargs()) as entries:
            for entry in entries:
                if self._entry_is_reparse(entry):
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                info = entry.stat(follow_symlinks=False)
                size = None if is_dir else info.st_size
                mtime_ns = getattr(info, "st_mtime_ns", None)
                if mtime_ns is None and getattr(info, "st_mtime", None) is not None:
                    mtime_ns = int(info.st_mtime * 1_000_000_000)
                item = {
                    "name": entry.name,
                    "is_dir": is_dir,
                    "size": size,
                }
                if details:
                    item["fingerprint"] = fileFingerprint(
                        "smb", getattr(info, "st_ino", None), mtime_ns
                    )
                result.append(item)
        result.sort(key=lambda x: (not x["is_dir"], x["name"].casefold()))
        return result

    @_smb_operation
    def mkdir(self, path):
        client = self._client()
        remote = self._remote(path)
        self._assert_no_reparse(client, remote, allow_missing=True)
        client.makedirs(remote, exist_ok=True, **self._connection_kwargs())

    @_smb_operation
    def delete(self, path):
        client = self._client()
        remote = self._remote(path, allow_root=False)
        self._assert_no_reparse(client, remote)
        self._delete(client, remote)

    def _delete(self, client, remote):
        kwargs = self._connection_kwargs()
        self._assert_no_reparse(client, remote)
        info = client.stat(remote, follow_symlinks=False, **kwargs)
        if not stat.S_ISDIR(info.st_mode):
            client.remove(remote, **kwargs)
            return
        with client.scandir(remote, **kwargs) as entries:
            children = []
            for entry in entries:
                if self._entry_is_reparse(entry):
                    raise ValueError("SMB symbolic links and reparse points are not supported")
                children.append((entry.path, entry.is_dir(follow_symlinks=False)))
        for child, is_dir in children:
            if is_dir:
                self._delete(client, child)
            else:
                client.remove(child, **kwargs)
        client.rmdir(remote, **kwargs)

    @_smb_operation
    def download(self, path, target, progress=None, cancel=None):
        client = self._client()
        remote = self._remote(path, allow_root=False)
        self._assert_no_reparse(client, remote)
        kwargs = self._connection_kwargs()
        size = client.stat(remote, follow_symlinks=False, **kwargs).st_size
        done = 0
        with client.open_file(remote, mode="rb", **kwargs) as source:
            while True:
                check_cancel(cancel)
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done / size if size else 1.0)
        if done != size:
            raise IOError("SMB download ended before the expected file size")
        if progress and size == 0:
            progress(1.0)

    @_smb_operation
    def upload(self, path, source, size=None, progress=None, cancel=None):
        client = self._client()
        destination = self._remote(path, allow_root=False)
        self._assert_no_reparse(client, destination, allow_missing=True)
        kwargs = self._connection_kwargs()
        try:
            if stat.S_ISDIR(client.stat(destination, follow_symlinks=False, **kwargs).st_mode):
                raise IsADirectoryError(path)
        except FileNotFoundError:
            pass
        client.makedirs(ntpath.dirname(destination), exist_ok=True, **kwargs)
        temporary = destination + ".taosync-" + uuid.uuid4().hex + ".part"
        done = 0
        try:
            with client.open_file(temporary, mode="wb", **kwargs) as target:
                while True:
                    check_cancel(cancel)
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done / size if size else 1.0)
            if size is not None and done != int(size):
                raise IOError("source stream ended before the expected file size")
            check_cancel(cancel)
            client.replace(temporary, destination, **kwargs)
            if progress and size == 0:
                progress(1.0)
        finally:
            try:
                if client.path.exists(temporary, **kwargs):
                    client.remove(temporary, **kwargs)
            except OSError:
                pass
