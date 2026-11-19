import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from service.alist import alistService
from service.alist.alistClient import AlistClient
from service.engine.taosyncClient import TaoSyncClient


class CreateDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.get_client = self.enterContext(patch.object(alistService, 'getClientById'))
        self.enterContext(patch.object(alistService, 'G', side_effect=lambda key: key))

    def test_root_is_rejected_before_accessing_any_engine(self):
        for parent in ('/', '//', '/./'):
            with self.subTest(parent=parent), self.assertRaisesRegex(ValueError, 'root_directory_creation_forbidden'):
                alistService.createDirectory(8, parent, '备份')
        self.get_client.assert_not_called()

    def test_external_nested_path(self):
        client = self.get_client.return_value = Mock(spec=AlistClient)
        client.fileListApi.return_value = {}
        for parent in ('/source/', '/target/nested/'):
            with self.subTest(parent=parent):
                self.assertEqual(alistService.createDirectory(8, parent, '备份'), parent + '备份/')
                self.get_client.assert_called_with(8)
                client.mkdir.assert_called_with(parent + '备份')

    def test_invalid_names_and_existing_entries(self):
        for name in ('', '  ', '.', '..', '../a', 'a/b', 'a\\b', 'a\0b', 123):
            with self.subTest(name=name), self.assertRaises(ValueError):
                alistService.createDirectory(1, '/folder/', name)
        self.get_client.assert_not_called()
        client = self.get_client.return_value
        client.fileListApi.return_value = {'file': 0, 'dir/': {}}
        for name in ('file', 'dir'):
            with self.subTest(name=name), self.assertRaises(FileExistsError):
                alistService.createDirectory(1, '/folder/', name)
        client.mkdir.assert_not_called()

    def test_builtin_mount_root_creates_real_directories(self):
        with tempfile.TemporaryDirectory() as root:
            mount = {'id': 1, 'name': 'local', 'driverType': 'local', 'config': {'root_path': root}}
            with patch('service.engine.taosyncClient.storageMapper.getMountList', return_value=[mount]):
                self.get_client.return_value = TaoSyncClient(1)
            with self.assertRaises(ValueError):
                alistService.createDirectory(1, '/', 'local')
            parent = alistService.createDirectory(1, '/local/', 'source')
            self.assertEqual(alistService.createDirectory(1, parent, 'child'), '/local/source/child/')
            self.assertTrue(Path(root, 'source', 'child').is_dir())
