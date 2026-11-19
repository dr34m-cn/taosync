"""A plaintext view of one subtree of an existing storage driver."""

import posixpath
import threading
from collections import Counter
from contextlib import contextmanager

from .base import StorageDriver, child_path, normalize_path
from ..backupCipher import BackupCipher, decrypted_size, encrypted_size, is_reserved_backup_name


class CryptDriver(StorageDriver):
    driver_type = 'crypt'
    allow_rapid_upload = False  # A restore must authenticate its source through EOF.
    requires_verified_eof = True

    def __init__(self, backing, root, passphrase, encrypt_dir_names):
        self.backing = backing
        self.root = normalize_path(root)
        self.cipher = BackupCipher(passphrase)
        self.encrypt_dir_names = encrypt_dir_names
        self._namespace_lock = threading.RLock()
        self._pending_files = Counter()

    def _name(self, name, is_dir):
        if is_dir and not self.encrypt_dir_names:
            return name
        return self.cipher.encode_name(name, is_dir)

    def _directory(self, path):
        result = self.root
        for part in normalize_path(path).strip('/').split('/'):
            if part:
                result = child_path(result, self._name(part, True))
        return result

    def _file(self, path):
        parent, name = posixpath.split(normalize_path(path, allow_root=False))
        return child_path(self._directory(parent), self._name(name, False))

    def _entry(self, entry):
        item = dict(entry)
        is_dir = item['is_dir']
        if not is_dir or self.encrypt_dir_names:
            item['name'] = self.cipher.decode_name(item['name'], is_dir)
        child_path('/', item['name'])
        if not is_dir:
            item['size'] = decrypted_size(item['size'])
        # The backing fingerprint is a valid change token. Its SHA-1 is of
        # ciphertext and cannot be advertised as a hash of the restored file.
        item.pop('sha1', None)
        return item

    def list(self, path, details=False):
        def visible(name, is_dir):
            return (is_dir and not self.encrypt_dir_names) or is_reserved_backup_name(name)

        rows = self.backing.list_filtered(self._directory(path), visible, details=details)
        entries = []
        kinds = {}
        for row in rows:
            entry = self._entry(row)
            if kinds.setdefault(entry['name'], entry['is_dir']) != entry['is_dir']:
                raise ValueError('a file and a directory share the same logical backup name')
            entries.append(entry)
        return sorted(entries, key=lambda item: (not item['is_dir'], item['name'].casefold()))

    def file_metadata(self, path):
        return self._entry(self.backing.file_metadata(self._file(path)))

    def _kind(self, parent, name):
        for entry in self.list(parent):
            if entry['name'] == name:
                return 'dir' if entry['is_dir'] else 'file'
        return None

    def mkdir(self, path):
        path = normalize_path(path)
        if path == '/':
            return
        if self.encrypt_dir_names:
            return self.backing.mkdir(self._directory(path))
        with self._namespace_lock:
            # File and directory components have different physical spellings.
            # Preserve the single logical namespace for every ancestor.
            parent = '/'
            for name in path.strip('/').split('/'):
                child = child_path(parent, name)
                if child in self._pending_files:
                    raise NotADirectoryError(child)
                kind = self._kind(parent, name)
                if kind == 'file':
                    raise NotADirectoryError(child)
                if kind is None:
                    break
                parent = child
            self.backing.mkdir(self._directory(path))

    @contextmanager
    def _reserve_file(self, path):
        if self.encrypt_dir_names:
            yield
            return
        # Keep the alternate clear directory name free while the backend is
        # still staging this file. Uploads of distinct files remain concurrent.
        with self._namespace_lock:
            parent, name = posixpath.split(path)
            try:
                kind = self._kind(parent, name)
            except FileNotFoundError:
                self.mkdir(parent)
            else:
                if kind == 'dir':
                    raise IsADirectoryError(path)
            self._pending_files[path] += 1
        try:
            yield
        finally:
            with self._namespace_lock:
                self._pending_files[path] -= 1
                if not self._pending_files[path]:
                    del self._pending_files[path]

    def upload(self, path, source, size=None, progress=None, cancel=None):
        path = normalize_path(path, allow_root=False)
        physical = self._file(path)
        with self._reserve_file(path):
            reader = self.cipher.encrypt_reader(source, size, cancel)
            return self.backing.upload(physical, reader, encrypted_size(size), progress, cancel)

    def download(self, path, target, progress=None, cancel=None):
        writer = self.cipher.decrypt_writer(target, cancel)
        self.backing.download(self._file(path), writer, progress, cancel)
        writer.finish()

    def delete(self, path):
        parent, name = posixpath.split(normalize_path(path, allow_root=False))
        kind = self._kind(parent, name)
        if kind is None:
            raise FileNotFoundError(path)
        if kind == 'dir':
            # A recursive backing delete would also remove foreign plaintext,
            # other keys' data or in-flight uploads that our view cannot own.
            pending = [self._directory(path)]
            while pending:
                directory = pending.pop()
                for row in self.backing.list(directory):
                    self._entry(row)
                    if row['is_dir']:
                        pending.append(child_path(directory, row['name']))
            self.backing.delete(self._directory(path))
        else:
            self.backing.delete(self._file(path))
