"""Filesystem boundaries shared by local mounts and the directory picker."""
import os
import errno
import re
import stat
import sys
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from pathlib import Path

from common.LNG import get_context_lang
from common.fileRetryReason import FileRetryError
from common.locales import t


sync_listing = ContextVar('sync_listing', default=False)


class LocalPathError(FileRetryError):
    def __str__(self):
        key, *params = self.args
        return t(key, get_context_lang()).format(*params)


def denied():
    return LocalPathError('local_path_protected')


def protected_paths():
    roots = [Path(__file__).resolve().parents[2], Path.cwd() / 'data']
    if getattr(sys, 'frozen', False):
        roots.append(Path(os.environ.get('STATICX_PROG_PATH') or sys.executable).resolve().parent)
        if os.getenv('TAO_UPDATE_DIR'):
            roots.append(Path(os.environ['TAO_UPDATE_DIR']).resolve().parent)
        for extra in (getattr(sys, '_MEIPASS', None), os.getenv('TAO_UPDATE_CHANNEL')):
            if extra:
                roots.append(Path(extra))
    if sys.platform.startswith('linux'):
        roots.extend(map(Path, ('/proc', '/dev', '/sys')))
    return roots


def canonical(path):
    expanded = Path(os.path.expanduser(path))
    if '..' in expanded.parts or (os.name == 'nt' and expanded.drive.startswith('\\\\')):
        raise denied()
    if os.name == 'nt' and any(part.endswith(('.', ' ')) or ':' in part or Path(part).is_reserved()
                               for part in expanded.parts if part != expanded.anchor):
        raise denied()
    resolved = expanded.resolve()
    if os.name == 'nt' and resolved.drive.startswith('\\\\'):
        raise denied()
    return resolved


def _mount_locations():
    # A Linux bind mount of a subdirectory has another pathname but retains its
    # filesystem device and its root within that filesystem.
    if not sys.platform.startswith('linux'):
        return []
    def unescape(raw):
        return os.fsdecode(re.sub(rb'\\([0-7]{3})', lambda m: bytes([int(m[1], 8)]), raw))
    mounts = []
    with open('/proc/self/mountinfo', 'rb') as rows:
        for row in rows:
            _, _, device, root, point, _ = row.split(b' ', 5)
            mounts.append((Path(unescape(point)), device, Path(unescape(root))))
    return sorted(mounts, key=lambda row: len(row[0].parts), reverse=True)


def _location(path, mounts):
    for point, device, root in mounts:
        if path.is_relative_to(point):
            return device, root / path.relative_to(point)
    return None, path


class LocalBoundary:
    def __init__(self):
        mounts = _mount_locations()
        self.roots = {root.resolve() for root in protected_paths()}
        # Include every mount exposing any part of a protected tree. Retain
        # lexical roots as well, so a filesystem mounted under the app is private.
        for root in tuple(self.roots):
            device, location = _location(root, mounts)
            for point, other_device, other_root in mounts:
                if device == other_device:
                    if location.is_relative_to(other_root):
                        self.roots.add(point / location.relative_to(other_root))
                    elif other_root.is_relative_to(location):
                        self.roots.add(point)
                if point.is_relative_to(root):
                    for alias, alias_device, alias_root in mounts:
                        if other_device == alias_device and other_root.is_relative_to(alias_root):
                            self.roots.add(alias / other_root.relative_to(alias_root))
                        elif other_device == alias_device and alias_root.is_relative_to(other_root):
                            self.roots.add(alias)
        self.identities = set()
        for root in self.roots:
            try:
                info = root.stat()
            except FileNotFoundError:
                continue
            self.identities.add((info.st_dev, info.st_ino))

    def check(self, path, *, subtree=False):
        if any(path.is_relative_to(root) or (subtree and root.is_relative_to(path)) for root in self.roots):
            raise denied()

    def check_directory(self, info):
        if (info.st_dev, info.st_ino) in self.identities:
            raise denied()

    def directory(self, path, create_from=None):
        self.check(path)
        return directory_handle(path, self, Path(create_from) if create_from else None)


def check_entry(info):
    if (getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT or
            not (stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1))):
        raise denied()


if os.name == 'nt':
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _open_handle = _kernel.CreateFileW
    _open_handle.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    _open_handle.restype = wintypes.HANDLE

    class _FileBasicInfo(ctypes.Structure):
        _fields_ = [(name, ctypes.c_int64) for name in ('created', 'accessed', 'modified', 'changed')] + [
            ('attributes', wintypes.DWORD)]

    _set_info = _kernel.SetFileInformationByHandle
    _set_info.argtypes = (wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
    _set_info.restype = wintypes.BOOL

    def _windows_fd(path, access):
        # Share read/write, but deny rename/delete until the parent operation completes.
        # OPEN_REPARSE_POINT inspects the entry itself; BACKUP_SEMANTICS permits directories.
        handle = _open_handle(str(path), access, 3, None, 3, 0x02200000, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)


def copy_file_stat(fd, info):
    if os.name == 'nt':
        # FILE_BASIC_INFO uses 100 ns ticks from 1601. Zero preserves the existing time.
        epoch = 116444736000000000
        attributes = info.st_file_attributes & stat.FILE_ATTRIBUTE_READONLY or stat.FILE_ATTRIBUTE_NORMAL
        basic = _FileBasicInfo(0, epoch + info.st_atime_ns // 100, epoch + info.st_mtime_ns // 100, 0, attributes)
        if not _set_info(msvcrt.get_osfhandle(fd), 0, ctypes.byref(basic), ctypes.sizeof(basic)):
            raise ctypes.WinError(ctypes.get_last_error())
    else:
        os.fchmod(fd, stat.S_IMODE(info.st_mode))
        os.utime(fd, ns=(info.st_atime_ns, info.st_mtime_ns))


@contextmanager
def directory_handle(path, boundary, create_from=None):
    """Pin parents while operating. POSIX callers use the returned directory fd."""
    with ExitStack() as stack:
        current = Path(path.anchor)
        parent = None
        for part in (path.anchor, *path.parts[1:]):
            current = current / part
            if create_from and current != create_from and current.is_relative_to(create_from):
                try:
                    os.mkdir(current if os.name == 'nt' else part, dir_fd=parent)
                except FileExistsError:
                    pass
            if os.name == 'nt':
                fd = _windows_fd(current, 0x80)  # FILE_READ_ATTRIBUTES
            else:
                try:
                    fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                except OSError as exc:
                    if exc.errno in (errno.ENOTDIR, errno.ELOOP) and os.path.islink(current):
                        raise denied() from exc
                    raise
            stack.callback(os.close, fd)
            info = os.fstat(fd)
            check_entry(info)
            boundary.check_directory(info)
            if os.name == 'nt':
                check_entry(os.lstat(current))
            if not stat.S_ISDIR(info.st_mode):
                raise NotADirectoryError(str(current))
            parent = None if os.name == 'nt' else fd
        yield parent


@contextmanager
def open_regular(path, parent):
    if os.name == 'nt':
        fd = _windows_fd(path, 0x80000000)  # GENERIC_READ
    else:
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise denied() from exc
            raise
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(fd)
        check_entry(info)
        if not stat.S_ISREG(info.st_mode):
            raise IsADirectoryError(str(path))
        yield stream
