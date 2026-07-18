import os
import re
import shutil
import uuid

from common.fileFingerprint import fileFingerprint

from .base import StorageDriver, check_cancel, normalize_path


class LocalDriver(StorageDriver):
    driver_type = "local"

    def __init__(self, config):
        root = config.get("root_path") or config.get("path")
        if not root:
            raise ValueError("local root_path is required")
        self.root = os.path.realpath(os.path.abspath(os.path.expanduser(str(root))))
        if not os.path.isdir(self.root):
            raise ValueError("local root_path must be an existing directory")

    def _resolve(self, path, allow_root=True):
        path = normalize_path(path, allow_root=allow_root)
        relative = path.lstrip("/").replace("/", os.sep)
        if os.name == "nt":
            for component in relative.split(os.sep) if relative else []:
                self._validate_windows_component(component)
        candidate = os.path.abspath(os.path.join(self.root, relative))
        try:
            if os.path.commonpath((self.root, candidate)) != self.root:
                raise ValueError("path escapes local root")
        except ValueError:
            raise ValueError("path escapes local root")
        current = self.root
        for part in relative.split(os.sep) if relative else []:
            current = os.path.join(current, part)
            if os.path.lexists(current) and os.path.islink(current):
                raise ValueError("symbolic links are not supported inside a local mount")
        resolved = os.path.realpath(candidate)
        if os.path.commonpath((self.root, resolved)) != self.root:
            raise ValueError("path escapes local root")
        return candidate

    @staticmethod
    def _validate_windows_component(component):
        if (
            not component
            or component.endswith((".", " "))
            or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in component)
        ):
            raise ValueError("invalid Windows local file name")
        stem = component.split(".", 1)[0].upper()
        if stem in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(
            r"(?:COM|LPT)[1-9]", stem
        ):
            raise ValueError("reserved Windows local file name")

    def list(self, path, details=False):
        target = self._resolve(path)
        if not os.path.isdir(target):
            raise FileNotFoundError(path)
        result = []
        with os.scandir(target) as entries:
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    resolved_entry = os.path.realpath(entry.path)
                    if os.path.commonpath((self.root, resolved_entry)) != self.root:
                        continue
                    is_dir = entry.is_dir(follow_symlinks=True)
                    info = entry.stat(follow_symlinks=False)
                    size = None if is_dir else info.st_size
                except (OSError, ValueError):
                    continue
                item = {
                    "name": entry.name,
                    "is_dir": is_dir,
                    "size": size,
                }
                if details:
                    item["fingerprint"] = fileFingerprint(
                        "local",
                        getattr(info, "st_dev", None),
                        getattr(info, "st_ino", None),
                        getattr(info, "st_mtime_ns", None),
                    )
                result.append(item)
        result.sort(key=lambda x: (not x["is_dir"], x["name"].casefold()))
        return result

    def mkdir(self, path):
        os.makedirs(self._resolve(path), exist_ok=True)

    def delete(self, path):
        target = self._resolve(path, allow_root=False)
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target)
        else:
            os.remove(target)

    def download(self, path, target, progress=None, cancel=None):
        source = self._resolve(path, allow_root=False)
        size = os.path.getsize(source)
        done = 0
        with open(source, "rb") as fp:
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

    def upload(self, path, source, size=None, progress=None, cancel=None):
        destination = self._resolve(path, allow_root=False)
        if os.path.isdir(destination):
            raise IsADirectoryError(path)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        temporary = destination + ".taosync-" + uuid.uuid4().hex + ".part"
        done = 0
        try:
            with open(temporary, "wb") as fp:
                while True:
                    check_cancel(cancel)
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    fp.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done / size if size else 1.0)
            if size is not None and done != int(size):
                raise IOError("source stream ended before the expected file size")
            check_cancel(cancel)
            os.replace(temporary, destination)
            if progress and size == 0:
                progress(1.0)
        finally:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass

    def copy(self, source_path, destination_path, size=None, progress=None, cancel=None):
        source = self._resolve(source_path, allow_root=False)
        destination = self._resolve(destination_path, allow_root=False)
        if os.path.isdir(destination):
            raise IsADirectoryError(destination_path)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        temporary = destination + ".taosync-" + uuid.uuid4().hex + ".part"
        total = os.path.getsize(source) if size is None else size
        done = 0
        try:
            with open(source, "rb") as src, open(temporary, "wb") as dst:
                while True:
                    check_cancel(cancel)
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done / total if total else 1.0)
            if total is not None and done != int(total):
                raise IOError("source file size changed during copy")
            check_cancel(cancel)
            shutil.copystat(source, temporary, follow_symlinks=False)
            os.replace(temporary, destination)
            if progress and total == 0:
                progress(1.0)
        finally:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass
