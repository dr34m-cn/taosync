import unittest
from unittest.mock import patch

from service.storage import storageService as storage


class FolderPickerTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(storage, '_requireTaoSync'))
        self.create = self.enterContext(patch.object(storage, 'createDriver'))
        self.enterContext(patch.object(storage.discoveryService, 'list_smb_shares', return_value=[{'name': 'Share'}]))
        self.driver = self.create.return_value
        self.client = self.enterContext(patch('service.engine.engineService.getClientById')).return_value

    def test_each_network_picker_lists_and_creates_under_configured_root(self):
        for kind in ('smb', 'ftp', 'sftp'):
            with self.subTest(kind=kind):
                req = dict(engineId=1, driverType=kind, path='/parent', config=dict(
                    root_path='/base', share='Share', host='server', username='person', password='test'))
                self.driver.list_filtered.return_value = [dict(name='child', is_dir=True)]
                self.assertEqual(storage.remoteFolder(req), {'directories': [{'path': '/parent/child', 'name': 'child'}]})
                self.assertEqual(self.create.call_args.args[1]['root_path'], '/base')
                self.assertEqual(self.driver.list_filtered.call_args.args[0], '/parent')
                self.assertEqual(storage.remoteFolder(dict(req, name='new'), create=True),
                                 {'directory': {'name': 'new', 'path': '/parent/new'}})
                self.driver.mkdir.assert_called_with('/parent/new')
                self.assertEqual(self.client._listingChange.call_args.args[1:], ('/parent/new', 'directory'))
                with self.assertRaises(FileExistsError):
                    storage.remoteFolder(dict(req, name='child'), create=True)
        self.assertEqual(self.driver.close.call_count, 3)

    def test_invalid_parent_or_child_is_rejected_before_connect(self):
        req = dict(engineId=1, driverType='ftp', path='/', config={})
        for fields in ({'path': 'relative'}, {'path': '/../other'}, {'name': '..'}, {'name': 'a/b'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                storage.remoteFolder(dict(req, **fields), create='name' in fields)
        self.create.assert_not_called()

    def test_ftp_password_is_not_reused_across_tls_downgrade(self):
        old = dict(engineId=1, driverType='ftp', config=dict(host='server', username='user', tls=True, password='old'))
        with patch.object(storage.storageMapper, 'getMountById', return_value=old):
            cfg = storage._networkRequestConfig(dict(engineId=1, mountId=2, config={'tls': False}), 'ftp')
        self.assertEqual(cfg['password'], '')
