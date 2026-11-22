import io
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

from service.storage.backupCipher import (BackupNamespaceError, InvalidBackupData,
                                         InvalidBackupName, ForeignBackupName)
from service.storage.drivers.aliyun import AliyunDriveDriver
from service.storage.drivers.base import stream_transfer
from service.storage.drivers.crypt import CryptDriver
from service.storage.drivers.local import LocalDriver
from service.storage.pathIdentity import mount_paths_overlap


class CryptDriverTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / 'vault').mkdir()
        self.backing = LocalDriver({'root_path': str(self.root)})
        self.view = CryptDriver(self.backing, '/vault', 'test key', False)

    def test_foreign_data_is_not_owned_by_the_view(self):
        self.view.mkdir('/nested')
        other = self.root / 'vault/nested/ordinary.txt'
        other.write_bytes(b'keep')
        self.assertEqual(self.view.list('/nested'), [])
        with self.assertRaises(ForeignBackupName):
            self.view.delete('/nested')
        self.assertEqual(other.read_bytes(), b'keep')
        with self.assertRaises(FileNotFoundError):
            self.view.delete('/nested/ordinary.txt')
        # Reserved names that cannot be authenticated must not look like a
        # successful empty source scan to a mirror job.
        (self.root / 'vault/tsb-1-damaged').touch()
        with self.assertRaises(InvalidBackupName):
            self.view.list('/')

    def test_files_and_clear_directories_share_one_logical_namespace(self):
        self.view.upload('/file', io.BytesIO(b'x'), 1)
        with self.assertRaises(NotADirectoryError):
            self.view.mkdir('/file/child')
        self.view.mkdir('/folder')
        with self.assertRaises(IsADirectoryError):
            self.view.upload('/folder', io.BytesIO(b'x'), 1)
        self.view.delete('/file')
        self.view.delete('/folder')
        self.assertEqual(self.view.list('/'), [])

    def test_small_file_uploads_do_not_enumerate_existing_siblings(self):
        with patch.object(self.backing, 'list', wraps=self.backing.list) as listing:
            for number in range(64):
                self.view.upload(f'/f{number}.txt', io.BytesIO(b'x'), 1)
            listing.assert_not_called()
        self.assertEqual(len(self.view.list('/')), 64)

    def test_long_unicode_names_restore_after_reopening_and_preserve_v1(self):
        directory = '文' * 64
        names = ['a' * 139, 'b' * 140, '备份' * 55 + '报告.txt', '文' * 250, 'a' * 300]
        for encrypted in (False, True):
            with self.subTest(encrypted=encrypted):
                view = CryptDriver(self.backing, '/vault', 'test key', encrypted)
                for index, name in enumerate(names):
                    view.upload(f'/{directory}/{name}', io.BytesIO(bytes([index])), 1)
                reopened = CryptDriver(self.backing, '/vault', 'test key', encrypted)
                self.assertEqual([r['name'] for r in reopened.list('/')], [directory])
                self.assertCountEqual([r['name'] for r in reopened.list('/' + directory)], names)
                for index, name in enumerate(names):
                    path = f'/{directory}/{name}'
                    self.assertEqual(reopened.file_metadata(path)['size'], 1)
                    restored = io.BytesIO()
                    reopened.download(path, restored)
                    self.assertEqual(restored.getvalue(), bytes([index]))
                    reopened.delete(path)
                reopened.delete('/' + directory)
                self.assertEqual(list((self.root / 'vault').iterdir()), [])

    def test_long_name_metadata_interruption_corruption_and_recovery(self):
        name = '雨' * 100
        real_upload = self.backing.upload

        def interrupt(path, *args):
            if '/tsb-2-' in path:
                raise OSError('interrupted before publish')
            return real_upload(path, *args)

        with patch.object(self.backing, 'upload', side_effect=interrupt), self.assertRaises(OSError):
            self.view.upload('/' + name, io.BytesIO(b'x'), 1)
        self.assertEqual(self.view.list('/'), [])
        self.view.upload('/' + name, io.BytesIO(b'x'), 1)
        record, = (self.root / 'vault').glob('tsb-n-*')
        good = record.read_bytes()
        record.write_bytes(good[:-1] + bytes([good[-1] ^ 1]))
        with self.assertRaises(BackupNamespaceError):
            self.view.list('/')
        with self.assertRaises(BackupNamespaceError):
            self.view.delete('/' + name)
        with self.assertRaises(BackupNamespaceError):
            self.view.upload('/' + name, io.BytesIO(b'y'), 1)
        record.unlink()
        with self.assertRaises(BackupNamespaceError):
            self.view.list('/')
        with self.assertRaises(BackupNamespaceError):
            self.view.upload('/' + name, io.BytesIO(b'z'), 1)
        record.write_bytes(good)
        restored = io.BytesIO()
        self.view.download('/' + name, restored)
        self.assertEqual(restored.getvalue(), b'x')

    def test_existing_unowned_bytes_cannot_be_overwritten_or_removed(self):
        self.view.mkdir('/child')
        for name in ('small', '长' * 128):
            logical = '/child/' + name
            self.view.upload(logical, io.BytesIO(b'x'), 1)
            physical = self.root / self.view._file(logical).lstrip('/')
            valid = physical.read_bytes()
            # Both correct-looking length and a copied magic prefix must fail.
            foreign = valid[:5] + b'-' * (len(valid) - 5)
            physical.write_bytes(foreign)
            for operation in (lambda: self.view.upload(logical, io.BytesIO(b'y'), 1),
                              lambda: self.view.delete(logical), lambda: self.view.delete('/child')):
                with self.assertRaises(BackupNamespaceError):
                    operation()
                self.assertEqual(physical.read_bytes(), foreign)
            physical.write_bytes(valid)
            self.view.delete(logical)

    def test_other_view_cannot_delete_while_long_file_upload_is_active(self):
        second = CryptDriver(self.backing, '/vault', 'test key', False)
        entered, resume = threading.Event(), threading.Event()
        name = '明' * 80

        class Source(io.BytesIO):
            def read(self, size):
                entered.set()
                if not resume.wait(timeout=10):
                    raise TimeoutError
                return super().read(size)

        with ThreadPoolExecutor(1) as executor:
            task = executor.submit(self.view.upload, '/nested/' + name, Source(b'first'), 5)
            try:
                self.assertTrue(entered.wait(5))
                for path in ('/nested', '/nested/' + name):
                    with self.assertRaises(BackupNamespaceError):
                        second.delete(path)
            finally:
                resume.set()
            task.result()
        self.assertEqual(second.list('/nested')[0]['name'], name)

    def test_restore_reencrypts_into_a_second_key_and_hides_ciphertext_hash(self):
        (self.root / 'second').mkdir()
        second = CryptDriver(self.backing, '/second', 'another key', True)
        data = b'abcd' * 100000
        self.view.upload('/nested/report', io.BytesIO(data), len(data))
        second.mkdir('/nested')
        meta = self.view.file_metadata('/nested/report')
        physical_metadata = {**self.backing.file_metadata(self.view._file('/nested/report')),
                             'sha1': 'ciphertext', 'contentHashes': {'md5': 'ciphertext'}}
        entry = self.view._entry(physical_metadata)
        self.assertNotIn('sha1', entry)
        self.assertNotIn('contentHashes', entry)
        stream_transfer(self.view, '/nested/report', second, '/nested/report', len(data), metadata=meta)
        restored = io.BytesIO()
        second.download('/nested/report', restored)
        self.assertEqual(restored.getvalue(), data)
        first_file, = (self.root / 'vault/nested').iterdir()
        second_file, = (p for p in (self.root / 'second').rglob('*') if p.is_file())
        self.assertNotEqual(first_file.name, second_file.name)
        self.assertNotEqual(first_file.read_bytes(), second_file.read_bytes())

    def test_exact_length_destinations_never_commit_an_unauthenticated_empty_file(self):
        self.view.upload('/empty', io.BytesIO(), 0)
        physical, = (self.root / 'vault').iterdir()
        wire = physical.read_bytes()
        physical.write_bytes(wire[:-1] + bytes([wire[-1] ^ 1]))
        destination = Mock()
        with self.assertRaises(InvalidBackupData):
            stream_transfer(self.view, '/empty', destination, '/empty', 0)
        destination.upload.assert_not_called()

    def test_cloud_upload_does_not_probe_or_spool_encrypted_or_decrypting_streams(self):
        cloud = Mock(rapid_upload=True, RAPID_UPLOAD_THRESHOLD=1)
        cloud._request.return_value = {}
        source = Mock(allow_rapid_upload=False)
        _, actual, consumed = AliyunDriveDriver._create_upload(cloud, {}, source, 20 * 1024 * 1024, None)
        self.assertIs(actual, source)
        self.assertFalse(consumed)
        source.read.assert_not_called()
        cloud._request.assert_called_once_with('/adrive/v1.0/openFile/create', {})

    def test_overlap_guard_resolves_the_backing_subtree_even_through_an_alias(self):
        base = {'id': 1, 'name': 'disk', 'driverType': 'local', 'config': {'root_path': str(self.root)}}
        alias = {**base, 'id': 2, 'name': 'alias', 'config': {'root_path': str(self.root / 'vault')}}
        overlay = {'id': 3, 'name': 'secret', 'driverType': 'crypt', 'config': {
            'target_mount_id': 1, 'target_path': '/vault', 'encrypt_dir_names': True}}
        mounts = [base, alias, overlay]
        for conflict in ('/disk', '/disk/vault', '/disk/vault/cipher', '/alias/cipher'):
            self.assertTrue(mount_paths_overlap(mounts, '/secret/name', conflict), conflict)
        self.assertFalse(mount_paths_overlap(mounts, '/secret', '/disk/other'))
        self.assertFalse(mount_paths_overlap(mounts, '/secret/a', '/secret/b'))
