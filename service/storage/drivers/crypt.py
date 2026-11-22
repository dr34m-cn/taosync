"""A plaintext view of one subtree of an existing storage driver."""

import io
import posixpath
import threading
import weakref
from collections import Counter
from contextlib import contextmanager

from .base import StorageDriver, child_path, normalize_path, check_cancel
from ..backupCipher import (BackupCipher, BackupNamespaceError, LONG_PREFIX, RECORD_PREFIX,
                            MAX_NAME_RECORD, OWNERSHIP_PREFIX_SIZE, decrypted_size, encrypted_size,
                            is_reserved_backup_name)


class _Namespace:
    def __init__(self):
        self.lock = threading.RLock()
        self.pending = Counter()


_namespaces = weakref.WeakValueDictionary()
_registry_lock = threading.Lock()


class _NameBuffer(io.BytesIO):
    def write(self, data):
        if self.tell() + len(data) > MAX_NAME_RECORD:
            raise BackupNamespaceError('crypt_name_record_invalid')
        return super().write(data)


class _PrefixComplete(Exception):
    pass


class _FilePrefix(io.BytesIO):
    def write(self, data):
        remaining = OWNERSHIP_PREFIX_SIZE - self.tell()
        if len(data) >= remaining:
            super().write(data[:remaining])
            raise _PrefixComplete
        return super().write(data)


class CryptDriver(StorageDriver):
    driver_type = 'crypt'
    allow_rapid_upload = False
    requires_verified_eof = True

    def __init__(self, backing, root, passphrase, encrypt_dir_names, namespace_id=None):
        self.backing = backing
        self.root = normalize_path(root)
        self.cipher = BackupCipher(passphrase)
        self.encrypt_dir_names = encrypt_dir_names
        # Jobs can construct separate views over the same physical mount.
        key = (backing if namespace_id is None else namespace_id, self.root)
        with _registry_lock:
            self._namespace = _namespaces.setdefault(key, _Namespace())

    def _record_path(self, directory, physical):
        return child_path(directory, RECORD_PREFIX + physical[len(LONG_PREFIX):].lower())

    def _write(self, path, source, size, create, progress=None, cancel=None):
        if create:
            upload_new = getattr(self.backing, 'upload_new', None)
            if upload_new is not None:
                return upload_new(path, source, size, progress, cancel)
        return self.backing.upload(path, source, size, progress, cancel)

    def _read_record(self, directory, physical):
        buffer = _NameBuffer()
        try:
            self.backing.download(self._record_path(directory, physical), buffer)
        except FileNotFoundError as exc:
            raise BackupNamespaceError('crypt_name_record_invalid') from exc
        return self.cipher.decode_record(physical, buffer.getvalue())

    def _component(self, directory, name, is_dir, prepare=False):
        if is_dir and not self.encrypt_dir_names:
            return child_path(directory, name)
        physical, record = self.cipher.storage_name(name)
        path = child_path(directory, physical)
        if record is not None:
            record_path = self._record_path(directory, physical)
            if prepare and self.backing.entry_kind(record_path) is None:
                # Publish metadata first. A process interruption can leave a valid
                # orphan record, but never a newly visible file with no mapping.
                if self.backing.entry_kind(path) is not None:
                    raise BackupNamespaceError('crypt_name_record_invalid')
                self._write(record_path, io.BytesIO(record), len(record), True)
            else:
                try:
                    stored = self._read_record(directory, physical)
                except BackupNamespaceError as exc:
                    if (isinstance(exc.__cause__, FileNotFoundError)
                            and self.backing.entry_kind(path) is None):
                        raise FileNotFoundError(path) from exc
                    raise
                if stored != name:
                    raise BackupNamespaceError('crypt_name_record_invalid')
        return path

    def _directory(self, path):
        result = self.root
        for part in normalize_path(path).strip('/').split('/'):
            if part:
                result = self._component(result, part, True)
        return result

    def _file(self, path):
        parent, name = posixpath.split(normalize_path(path, allow_root=False))
        return self._component(self._directory(parent), name, False)

    def _entry(self, entry, directory=None, names=None):
        item = dict(entry)
        is_dir = item['is_dir']
        if not is_dir or self.encrypt_dir_names:
            physical = item['name'].lower()
            if physical.startswith(LONG_PREFIX):
                item['name'] = (names or {}).get(physical) or self._read_record(directory, physical)
            else:
                item['name'] = self.cipher.decode_name(item['name'], is_dir)
        child_path('/', item['name'])
        if not is_dir:
            item['size'] = decrypted_size(item['size'])
        item.pop('sha1', None)
        item.pop('contentHashes', None)
        return item

    def _entries(self, directory, rows):
        names = {}
        data = []
        for row in rows:
            name = row['name'].lower()
            if not row['is_dir'] and name.startswith(RECORD_PREFIX):
                alias = LONG_PREFIX + name[len(RECORD_PREFIX):]
                names[alias] = self._read_record(directory, alias)
            else:
                data.append(row)
        entries = []
        kinds = {}
        for row in data:
            entry = self._entry(row, directory, names)
            if entry['name'] in kinds:
                raise BackupNamespaceError('crypt_name_conflict')
            kinds[entry['name']] = entry['is_dir']
            entries.append(entry)
        return entries

    def list(self, path, details=False):
        def visible(name, is_dir):
            return (is_dir and not self.encrypt_dir_names) or is_reserved_backup_name(name)
        directory = self._directory(path)
        rows = self.backing.list_filtered(directory, visible, details=details)
        return sorted(self._entries(directory, rows), key=lambda item: (not item['is_dir'], item['name'].casefold()))

    def file_metadata(self, path):
        path = normalize_path(path, allow_root=False)
        physical = self._file(path)
        item = self.backing.file_metadata(physical)
        # _file has already authenticated any long-name record.
        return self._entry(item, posixpath.dirname(physical), {item['name'].lower(): posixpath.basename(path)})

    def _kind(self, parent, name):
        directory = self._directory(parent)
        encoded, _ = self.cipher.storage_name(name)
        kind = self.backing.entry_kind(child_path(directory, encoded))
        if self.encrypt_dir_names:
            return kind
        if self._clear_directory_exists(directory, name):
            if kind == 'file':
                raise BackupNamespaceError('crypt_name_conflict')
            return 'dir'
        return 'file' if kind == 'file' else None

    def _clear_directory_exists(self, directory, name):
        try:
            return self.backing.entry_kind(child_path(directory, name)) == 'dir'
        except OSError:
            if len(name.encode('utf-8')) <= 255:
                raise
            # SFTP v3 can report an unrepresentable server-side component as
            # a generic FAILURE. A successful parent listing resolves it.
            return any(row['is_dir'] and row['name'].casefold() == name.casefold()
                       for row in self.backing.list(directory))

    def _prepare_directory(self, path):
        directory = self.root
        logical = '/'
        for part in path.strip('/').split('/') if path != '/' else []:
            logical = child_path(logical, part)
            if logical in self._namespace.pending:
                raise NotADirectoryError(logical)
            if not self.encrypt_dir_names:
                encoded, _ = self.cipher.storage_name(part)
                if self.backing.entry_kind(child_path(directory, encoded)) == 'file':
                    raise NotADirectoryError(logical)
            directory = self._component(directory, part, True, prepare=True)
            kind = self.backing.entry_kind(directory)
            if kind == 'file':
                raise NotADirectoryError(logical)
            if kind != 'dir':
                self.backing.mkdir(directory)
        return directory

    def mkdir(self, path):
        with self._namespace.lock:
            self._prepare_directory(normalize_path(path))

    def _verify_file(self, physical, size=None):
        range_read = getattr(self.backing, 'read_range', None)
        if range_read is not None:
            if size is None:
                size = self.backing.file_metadata(physical)['size']
            data = range_read(physical, 0, min(size, OWNERSHIP_PREFIX_SIZE)) if size else b''
        else:
            prefix = _FilePrefix()
            try:
                self.backing.download(physical, prefix)
            except _PrefixComplete:
                pass
            data = prefix.getvalue()
        self.cipher.authenticate_prefix(data)

    @contextmanager
    def _reserve_file(self, path):
        parent, name = posixpath.split(path)
        with self._namespace.lock:
            # Upload supports missing parent directories on all backing drivers.
            directory = self._prepare_directory(parent)
            if not self.encrypt_dir_names and self._clear_directory_exists(directory, name):
                raise IsADirectoryError(path)
            physical = self._component(directory, name, False, prepare=True)
            kind = self.backing.entry_kind(physical)
            if kind == 'dir':
                raise IsADirectoryError(path)
            if kind is not None:
                self._verify_file(physical)
            self._namespace.pending[path] += 1
        try:
            yield physical, kind is None
        finally:
            with self._namespace.lock:
                self._namespace.pending[path] -= 1
                if not self._namespace.pending[path]:
                    del self._namespace.pending[path]

    def upload(self, path, source, size=None, progress=None, cancel=None):
        path = normalize_path(path, allow_root=False)
        check_cancel(cancel)
        with self._reserve_file(path) as (physical, create):
            reader = self.cipher.encrypt_reader(source, size, cancel)
            return self._write(physical, reader, encrypted_size(size), create, progress, cancel)

    def download(self, path, target, progress=None, cancel=None):
        writer = self.cipher.decrypt_writer(target, cancel)
        self.backing.download(self._file(path), writer, progress, cancel)
        writer.finish()

    def delete(self, path):
        path = normalize_path(path, allow_root=False)
        parent, name = posixpath.split(path)
        with self._namespace.lock:
            if any(p == path or p.startswith(path + '/') for p in self._namespace.pending):
                raise BackupNamespaceError('crypt_path_busy')
            kind = self._kind(parent, name)
            if kind is None:
                raise FileNotFoundError(path)
            directory = self._directory(parent)
            physical = self._component(directory, name, kind == 'dir')
            if kind == 'dir':
                # Validate foreign entries AND orphan metadata before recursively
                # deleting a subtree, including ciphertext made with other keys.
                pending = [physical]
                while pending:
                    subtree = pending.pop()
                    rows = self.backing.list(subtree)
                    self._entries(subtree, rows)
                    for row in rows:
                        child = child_path(subtree, row['name'])
                        if row['is_dir']:
                            pending.append(child)
                        elif not row['name'].lower().startswith(RECORD_PREFIX):
                            self._verify_file(child, row.get('size'))
            else:
                self._verify_file(physical)
            self.backing.delete(physical)
            alias = posixpath.basename(physical)
            if (kind != 'dir' or self.encrypt_dir_names) and alias.startswith(LONG_PREFIX):
                self.backing.delete(self._record_path(directory, alias))
