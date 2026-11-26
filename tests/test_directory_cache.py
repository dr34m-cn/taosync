import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common import sqlBase, sqlInit
from common.directoryCache import DirectoryCache
from mapper import storageMapper
from service.storage.storageService import _cacheDays


class DirectoryCacheTests(unittest.TestCase):
    def setUp(self):
        tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(sqlBase, 'getConfig', return_value={
            'db': {'dbname': str(Path(tmp) / 'cache.db')}, 'server': {'password': 'test'}}))
        # Initialize the real migration chain against an isolated database.
        self.enterContext(patch.object(sqlInit, 'getConfig', sqlBase.getConfig))
        sqlInit.init_sql()
        mid = storageMapper.addMount(dict(engineId=1, name='cloud', driverType='aliyun', config={}))
        self.mount = storageMapper.getMountById(mid)
        self.cache = DirectoryCache(persistent=True)

    def put(self, path, entries=(), **kwargs):
        self.cache.record(self.mount, path, list(entries), True, self.cache.revision, **kwargs)

    def test_default_expiry_survives_restart_and_delta_does_not_extend_ttl(self):
        with patch('common.directoryCache.time.time', return_value=100):
            self.put('/')
        self.cache = DirectoryCache(persistent=True)
        with patch('common.directoryCache.time.time', return_value=100 + 29 * 86400):
            self.cache.change(self.mount, '/new', 'file', 4)
            self.assertEqual(self.cache.read(self.mount, '/')[0]['size'], 4)
            self.assertIsNone(self.cache.read(self.mount, '/', source=True))
        with patch('common.directoryCache.time.time', return_value=100 + 30 * 86400):
            self.assertIsNone(self.cache.read(self.mount, '/'))

    def test_zero_permanent_and_stale_client_after_disable(self):
        mid = self.mount['id']
        storageMapper.updateCachePolicy(mid, 5, -1)
        with patch('common.directoryCache.time.time', return_value=1):
            self.put('/')
        self.assertEqual(self.cache.read(self.mount, '/'), [])
        storageMapper.updateCachePolicy(mid, 5, 0)
        disabled = storageMapper.getMountById(mid)
        self.cache.record(disabled, '/', [], True, self.cache.revision)
        self.assertIsNone(self.cache.read(disabled, '/'))
        storageMapper.updateCachePolicy(mid, 5, -1)
        self.put('/')  # The previous generation must not refill a re-enabled cache.
        self.cache.record(disabled, '/', [], True, self.cache.revision)
        self.mount = storageMapper.getMountById(mid)
        self.assertIsNone(self.cache.read(self.mount, '/'))
        self.put('/')
        self.assertEqual(self.cache.read(self.mount, '/'), [])

    def test_local_changes_preserve_siblings_and_reject_inflight_stale_listing(self):
        for path in ('/', '/a', '/a/b', '/ab'):
            self.put(path)
        revision = self.cache.revision
        self.cache.change(self.mount, '/a/b/c', 'directory')
        self.cache.record(self.mount, '/a/b', [], True, revision)
        self.assertEqual(self.cache.read(self.mount, '/a/b')[0]['name'], 'c')
        self.cache.change(self.mount, '/a', 'delete')
        self.assertIsNone(self.cache.read(self.mount, '/a/b'))
        self.assertEqual(self.cache.read(self.mount, '/ab'), [])
        self.assertEqual(self.cache.read(self.mount, '/'), [])

    def test_folder_picker_patches_by_actual_cloud_parent(self):
        self.put('/a', identity=('drive', 'parent'))
        self.put('/b', identity=('other-drive', 'parent'))
        self.cache.cloudMkdir('drive', 'parent', 'new')
        self.assertEqual(self.cache.read(self.mount, '/a')[0]['name'], 'new')
        self.assertEqual(self.cache.read(self.mount, '/b'), [])

    def test_nested_cloud_alias_updates_only_the_matching_subtree(self):
        mid = storageMapper.addMount(dict(engineId=1, name='nested', driverType='aliyun',
                                          config={'root_folder_id': 'inside'}))
        nested = storageMapper.getMountById(mid)
        self.put('/Shows', identity=('drive', 'inside'))
        self.assertEqual(self.cache.cloudAliasPath(self.mount, '/Shows/Title', nested), '/Title')
        self.assertEqual(self.cache.cloudAliasPath(nested, '/Title', self.mount), '/Shows/Title')
        self.assertIsNone(self.cache.cloudAliasPath(self.mount, '/Other', nested))

    @patch('service.storage.storageService.get_context_lang', return_value='en')
    def test_policy_validation(self, _lang):
        for value in (0, -1, 30):
            self.assertEqual(_cacheDays(value), value)
        for value in (-2, 0.5, '0', True, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _cacheDays(value)
