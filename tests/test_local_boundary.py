import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from service.storage import discoveryService, localAccess
from service.storage.drivers.local import LocalDriver
from common import LNG
from common.fileRetryReason import renderReason, storedReason


class LocalBoundaryTest(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.private = root / 'install' / 'TaoSync'
        self.private.mkdir(parents=True)
        self.database = self.private / 'test.db'
        self.database.write_bytes(b'fixture')
        self.public = root / 'public'
        self.public.mkdir()
        self.enterContext(patch.object(localAccess, 'protected_paths', return_value=[self.private]))
        self.driver = LocalDriver({'root_path': str(root)})

    def test_picker_existing_mount_and_recursive_delete(self):
        path = '/install/TaoSync/test.db'
        self.assertEqual(self.driver.list('/install'), [])
        self.assertEqual(discoveryService.localBrowse(str(self.private.parent))['directories'], [])
        for operation in (
            lambda: discoveryService.localBrowse(str(self.private)),
            lambda: LocalDriver({'root_path': str(self.private)}),
            lambda: self.driver.list('/install/TaoSync'),
            lambda: self.driver.file_metadata(path),
            lambda: self.driver.download(path, io.BytesIO()),
            lambda: self.driver.read_range(path, 0, 1),
            lambda: self.driver.upload(path, io.BytesIO(b'new')),
            lambda: self.driver.mkdir('/install/TaoSync/sub'),
            lambda: self.driver.copy(path, '/public/copy'),
            lambda: self.driver.copy('/public/copy', path),
            lambda: self.driver.delete('/install'),
            lambda: self.driver.delete(path),
            lambda: self.driver.list('/public/../install/TaoSync'),
        ):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                operation()
        self.assertEqual(self.database.read_bytes(), b'fixture')
        self.assertEqual(list(self.public.iterdir()), [])

    def test_linked_file_is_hidden_and_refused_for_read_and_write(self):
        os.link(self.database, self.public / 'linked')
        self.assertEqual(self.driver.list('/public'), [])
        with self.assertRaises(ValueError):
            self.driver.download('/public/linked', io.BytesIO())
        with self.assertRaises(ValueError):
            self.driver.upload('/public/linked', io.BytesIO(b'new'))
        self.assertEqual(self.database.read_bytes(), b'fixture')

    def test_denial_uses_viewer_language_in_requests_and_saved_history(self):
        with self.assertRaises(localAccess.LocalPathError) as caught:
            self.driver.list('/install/TaoSync')
        text, reason = storedReason(caught.exception)
        self.assertIsNone(text)
        for language, fragment in (('zh_CN', '此本地路径受保护'), ('en', 'This local path is protected')):
            with patch.object(LNG._local, 'lang', language, create=True):
                self.assertIn(fragment, str(caught.exception))
                self.assertIn(fragment, renderReason({'retryReason': reason})['errMsg'])

    def test_linked_directory_is_refused(self):
        alias = self.public / 'alias'
        if os.name == 'nt':
            import _winapi
            _winapi.CreateJunction(str(self.private), str(alias))
        else:
            alias.symlink_to(self.private, target_is_directory=True)
        self.assertEqual(self.driver.list('/public'), [])
        for operation in (lambda: LocalDriver({'root_path': str(alias)}),
                          lambda: discoveryService.localBrowse(str(alias)),
                          lambda: self.driver.read_range('/public/alias/test.db', 0, 1),
                          lambda: self.driver.mkdir('/public/alias/new')):
            with self.assertRaises((OSError, ValueError)):
                operation()

    def test_inaccessible_protected_root_stat_keeps_lexical_protection(self):
        real_stat = Path.stat
        protected = self.private

        def guarded_stat(path_self, *args, **kwargs):
            if path_self == protected:
                raise PermissionError('SELinux denied')
            return real_stat(path_self, *args, **kwargs)

        with patch.object(Path, 'stat', guarded_stat):
            boundary = localAccess.LocalBoundary()
        with self.assertRaises(localAccess.LocalPathError):
            boundary.check(protected)
        with self.assertRaises(localAccess.LocalPathError):
            boundary.check(protected / 'test.db')
