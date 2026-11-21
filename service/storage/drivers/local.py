import os
import stat
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath

from common.fileFingerprint import fileFingerprint
from service.storage.localAccess import LocalBoundary, canonical, check_entry, denied, open_regular, copy_file_stat

from .base import StorageDriver, check_cancel, normalize_path, transfer_temp_name


class LocalDriver(StorageDriver):
    driver_type = "local"
    supports_random_read = True

    def __init__(self, config):
        root = config.get("root_path") or config.get("path")
        if not root:
            raise ValueError("local root_path is required")
        self.boundary = LocalBoundary()
        root = canonical(str(root))
        self.boundary.check(root)
        self.root = str(root)
        if not os.path.isdir(self.root):
            raise ValueError("local root_path must be an existing directory")

    def _resolve(self, path, allow_root=True):
        if '..' in str(path).replace('\\', '/').split('/'):
            raise denied()
        path = normalize_path(path, allow_root=allow_root)
        relative = path.lstrip("/").replace("/", os.sep)
        if os.name == "nt":
            for component in relative.split(os.sep) if relative else []:
                self._validate_windows_component(component)
        candidate = Path(self.root, relative)
        if not candidate.is_relative_to(self.root):
            raise denied()
        self.boundary.check(candidate)
        return candidate

    @staticmethod
    def _validate_windows_component(component):
        if (
            not component
            or component.endswith((".", " "))
            or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in component)
        ):
            raise ValueError("invalid Windows local file name")
        if PureWindowsPath(component).is_reserved():
            raise ValueError("reserved Windows local file name")

    def list(self, path, details=False):
        target = self._resolve(path)
        result = []
        with self.boundary.directory(target) as fd, os.scandir(target if fd is None else fd) as entries:
            for entry in entries:
                try:
                    self.boundary.check(target / entry.name)
                    info = entry.stat(follow_symlinks=False)
                    # DirEntry on Windows omits the link count and inode.
                    check_entry(os.lstat(entry.path) if os.name == "nt" else info)
                    is_dir = stat.S_ISDIR(info.st_mode)
                    size = None if is_dir else info.st_size
                except (OSError, ValueError):
                    continue
                item = {
                    "name": entry.name,
                    "is_dir": is_dir,
                    "size": size,
                }
                if details:
                    item["modified_at"] = info.st_mtime
                    item["created_at"] = getattr(info, "st_birthtime", info.st_ctime if os.name == "nt" else None)
                    item["fingerprint"] = fileFingerprint(
                        "local",
                        getattr(info, "st_dev", None),
                        getattr(info, "st_ino", None),
                        getattr(info, "st_mtime_ns", None),
                    )
                result.append(item)
        result.sort(key=lambda x: (not x["is_dir"], x["name"].casefold()))
        return result

    def file_metadata(self, path):
        target = self._resolve(path, allow_root=False)
        with self.boundary.directory(target.parent) as fd:
            info = os.stat(target if fd is None else target.name, dir_fd=fd, follow_symlinks=False)
            check_entry(info)
        if stat.S_ISDIR(info.st_mode):
            raise IsADirectoryError(path)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("local special files are not supported")
        # Match existing Windows DirEntry fingerprints (device/inode are zero)
        # so the optimization does not invalidate saved source snapshots.
        device = 0 if os.name == "nt" else getattr(info, "st_dev", None)
        inode = 0 if os.name == "nt" else getattr(info, "st_ino", None)
        return {
            "name": os.path.basename(target), "is_dir": False, "size": info.st_size,
            "modified_at": info.st_mtime,
            "created_at": getattr(info, "st_birthtime", info.st_ctime if os.name == "nt" else None),
            "fingerprint": fileFingerprint("local", device, inode, getattr(info, "st_mtime_ns", None)),
        }

    def mkdir(self, path):
        with self.boundary.directory(self._resolve(path), create_from=self.root):
            pass

    def delete(self, path):
        target = self._resolve(path, allow_root=False)
        self._delete(target)

    def _delete(self, target):
        self.boundary.check(target, subtree=True)
        with self.boundary.directory(target.parent) as parent:
            name = target if parent is None else target.name
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            check_entry(info)
            if stat.S_ISDIR(info.st_mode):
                with self.boundary.directory(target) as fd:
                    for child in os.listdir(target if fd is None else fd):
                        self._delete(target / child)
                os.rmdir(name, dir_fd=parent)
            else:
                os.unlink(name, dir_fd=parent)

    def download(self, path, target, progress=None, cancel=None):
        source = self._resolve(path, allow_root=False)
        done = 0
        with self.boundary.directory(source.parent) as parent, open_regular(source, parent) as fp:
            size = os.fstat(fp.fileno()).st_size
            while True:
                check_cancel(cancel)
                chunk = fp.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done / size if size else 1.0)
        if done != size:
            raise IOError("local file changed during download")
        if progress and size == 0:
            progress(1.0)

    def read_range(self, path, offset, length, cancel=None):
        check_cancel(cancel)
        path = self._resolve(path, allow_root=False)
        with self.boundary.directory(path.parent) as fd, open_regular(path, fd) as source:
            source.seek(offset)
            data = source.read(length)
        check_cancel(cancel)
        if len(data) != length:
            raise IOError("source file changed during range read")
        return data

    @contextmanager
    def _output(self, destination):
        with self.boundary.directory(destination.parent, create_from=self.root) as fd:
            name = destination if fd is None else destination.name
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                check_entry(info)
                if stat.S_ISDIR(info.st_mode):
                    raise IsADirectoryError(str(destination))
            except FileNotFoundError:
                pass
            temporary = transfer_temp_name()
            if fd is None:
                temporary = destination.parent / temporary
            handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0),
                             0o666, dir_fd=fd)
            try:
                with os.fdopen(handle, 'wb') as fp:
                    yield fp
                os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=fd)
                except FileNotFoundError:
                    pass

    def upload(self, path, source, size=None, progress=None, cancel=None):
        destination = self._resolve(path, allow_root=False)
        with self._output(destination) as fp:
            self._transfer(source, fp, size, progress, cancel)

    @staticmethod
    def _transfer(source, output, size, progress, cancel):
        done = 0
        while True:
            check_cancel(cancel)
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            done += len(chunk)
            if progress:
                progress(done / size if size else 1.0)
        if size is not None and done != int(size):
            raise IOError("source stream ended before the expected file size")
        check_cancel(cancel)
        if progress and size == 0:
            progress(1.0)

    def copy(self, source_path, destination_path, size=None, progress=None, cancel=None, metadata=None):
        source = self._resolve(source_path, allow_root=False)
        destination = self._resolve(destination_path, allow_root=False)
        with self.boundary.directory(source.parent) as fd, open_regular(source, fd) as src:
            info = os.fstat(src.fileno())
            with self._output(destination) as dst:
                self._transfer(src, dst, info.st_size if size is None else size, progress, cancel)
                dst.flush()
                copy_file_stat(dst.fileno(), info)
