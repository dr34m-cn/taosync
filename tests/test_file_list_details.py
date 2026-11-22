import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from service.alist.alistClient import AlistClient
from service.engine.taosyncClient import TaoSyncClient
from service.storage.drivers.smb import SmbDriver
from service.storage.drivers.local import LocalDriver
from service.storage.drivers.base import StorageDriver


class AlistFileListDetailTests(unittest.TestCase):
    @staticmethod
    def client():
        with patch.object(AlistClient, 'getUser'):
            client = AlistClient('http://alist.test', 'test-token')
        return client

    def test_detail_api_adds_opaque_fingerprint_and_legacy_api_keeps_shape(self):
        response = {
            'total': 2,
            'content': [
                {
                    'name': 'folder',
                    'is_dir': True,
                    'size': 0,
                    'modified': '2026-07-17T01:02:03Z',
                    'hash_info': None,
                },
                {
                    'name': 'payload.bin',
                    'is_dir': False,
                    'size': 4,
                    'modified': '2026-07-17T01:02:03Z',
                    'hash_info': {'sha1': 'raw-backend-hash'},
                },
            ]
        }
        client = self.client()
        with patch.object(client, 'post', return_value=response), \
                patch.object(client, '_storageDriverMap', return_value={}):
            details = client.fileListDetailApi('/source/')
            legacy = client.fileListApi('/source/')

        self.assertEqual(legacy, {'folder/': {}, 'payload.bin': 4})
        self.assertEqual(details['payload.bin']['size'], 4)
        self.assertTrue(details['payload.bin']['fingerprint'].startswith('alist:sha256:'))
        self.assertNotIn('raw-backend-hash', details['payload.bin']['fingerprint'])

    def test_directory_picker_reads_later_pages_and_refreshes_only_once(self):
        client = self.client()
        pages = [{'content': [{'name': 'file', 'is_dir': False}], 'total': 2},
                 {'content': [{'name': 'folder', 'is_dir': True}], 'total': 2}]
        with patch.object(client, 'post', side_effect=pages) as post, \
                patch.object(client, '_storageDriverMap', return_value={}), \
                patch.object(client, 'checkWait') as wait:
            self.assertEqual(client.filePathList('/cloud'), [{'path': 'folder'}])
        requests = [call.kwargs['data'] for call in post.call_args_list]
        self.assertEqual([(r['page'], r['refresh']) for r in requests], [(1, True), (2, False)])
        self.assertEqual(wait.call_count, 2)

    def test_short_pages_without_a_total_continue_until_empty(self):
        client = self.client()
        pages = [{'content': [{'name': name, 'is_dir': False, 'size': 0}]} for name in ('a', 'b')]
        with patch.object(client, 'post', side_effect=[*pages, {'content': None}]):
            self.assertEqual(client.fileListApi('/', useCache=1), {'a': 0, 'b': 0})

    def test_inconsistent_directory_pages_are_not_returned_as_a_complete_listing(self):
        client = self.client()
        first = {'content': [{'name': 'first', 'is_dir': False, 'size': 1}], 'total': 2}
        for second in (first, {'content': None, 'total': 2}, {'content': [], 'total': 1}):
            with self.subTest(second=second), patch.object(client, 'post', side_effect=[first, second]), \
                    self.assertRaises(ValueError):
                client.fileListApi('/source', useCache=1)

    def test_duplicate_in_a_single_page_is_rejected_before_finishing(self):
        client = self.client()
        rows = [{'name': 'a', 'is_dir': False, 'size': 1}] * 2
        for page in (1, 2):
            responses = [{'content': [{'name': 'first', 'is_dir': False, 'size': 2}], 'total': 3}] if page == 2 else []
            responses.append({'content': rows, 'total': page + 1})
            with self.subTest(page=page), patch.object(client, 'post', side_effect=responses), self.assertRaises(ValueError) as caught:
                client.fileListApi('/source', useCache=1)
            self.assertEqual(caught.exception.args, ('alist_duplicate_directory_page', '/source', page))
            with patch('common.LNG.get_context_lang', return_value='en'):
                self.assertIn(f'page {page}', str(caught.exception))
            with patch('common.LNG.get_context_lang', return_value='zh_CN'):
                self.assertIn(f'第 {page} 页', str(caught.exception))


class TaoSyncFileListDetailTests(unittest.TestCase):
    def test_same_mount_stream_copy_reads_metadata_once(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'source').write_bytes(b'payload')
            mounts = [{'id': 1, 'name': 'local', 'driverType': 'local',
                       'config': {'root_path': root}}]
            with patch('service.engine.taosyncClient.storageMapper.getMountList', return_value=mounts):
                client = TaoSyncClient(1)
            driver = client.mounts['local']['driver']
            driver.mkdir('/target')
            with patch.object(driver, 'copy', StorageDriver.copy.__get__(driver)), \
                    patch.object(driver, 'file_metadata', wraps=driver.file_metadata) as metadata:
                task_id = client.copyFile('/local', '/local/target', 'source')
                client.waitTask(task_id, 5)
                self.assertEqual(client.taskInfo(task_id)['state'], 2)
                metadata.assert_called_once_with('/source')
            self.assertEqual(Path(root, 'target', 'source').read_bytes(), b'payload')

    def test_local_file_metadata_does_not_scan_siblings(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'file').write_bytes(b'data')
            Path(root, 'folder').mkdir()
            driver = LocalDriver({'root_path': root})
            expected = next(item for item in driver.list('/', details=True) if item['name'] == 'file')
            with patch.object(driver, 'list', side_effect=AssertionError('directory scan')), \
                    patch('os.scandir', side_effect=AssertionError('directory scan')):
                self.assertEqual(driver.file_metadata('/file'), expected)
                with self.assertRaises(FileNotFoundError):
                    driver.file_metadata('/missing')
                with self.assertRaises(IsADirectoryError):
                    driver.file_metadata('/folder')
                with self.assertRaises(ValueError):
                    driver.file_metadata('/../file')

    def test_local_details_track_same_size_replacement_without_changing_legacy_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload = root / 'payload.bin'
            payload.write_bytes(b'GOOD')
            mounts = [{
                'id': 91,
                'engineId': 1,
                'name': 'local',
                'driverType': 'local',
                'config': {'root_path': str(root)},
                'enabled': 1,
                'authVersion': 1,
            }]
            with patch(
                'service.engine.taosyncClient.storageMapper.getMountList',
                return_value=mounts,
            ):
                client = TaoSyncClient(1)

            first = client.fileListDetailApi('/local/')
            legacy = client.fileListApi('/local/')
            stat_result = payload.stat()
            payload.write_bytes(b'EVIL')
            os.utime(
                payload,
                ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 1_000_000),
            )
            second = client.fileListDetailApi('/local/')

        self.assertEqual(legacy, {'payload.bin': 4})
        self.assertEqual(first['payload.bin']['size'], second['payload.bin']['size'])
        self.assertNotEqual(
            first['payload.bin']['fingerprint'],
            second['payload.bin']['fingerprint'],
        )
        self.assertNotIn(str(root), first['payload.bin']['fingerprint'])


class SmbFileListDetailTests(unittest.TestCase):
    def test_smb_stat_metadata_is_available_without_changing_default_list(self):
        info = SimpleNamespace(st_size=4, st_ino=123, st_mtime_ns=456)
        entry = SimpleNamespace(
            name='payload.bin',
            smb_info=SimpleNamespace(file_attributes=0),
            is_symlink=lambda: False,
            is_dir=lambda follow_symlinks=False: False,
        )

        @contextmanager
        def scan_entries(*_args, **_kwargs):
            yield [entry]

        client = SimpleNamespace(scandir=scan_entries, stat=Mock(return_value=info))
        driver = SmbDriver({'host': 'server', 'share': 'share', 'port': 1445})
        self.addCleanup(driver.close)
        driver._client = lambda: client
        driver._assert_no_reparse = lambda *_args, **_kwargs: None

        legacy = driver.list('/')
        detailed = driver.list('/', details=True)

        self.assertEqual(
            legacy, [{'name': 'payload.bin', 'is_dir': False, 'size': 4}]
        )
        self.assertTrue(detailed[0]['fingerprint'].startswith('smb:sha256:'))
        self.assertEqual(client.stat.call_count, 2)
        for call in client.stat.call_args_list:
            self.assertEqual(call.args, (r'\\server\share\payload.bin',))
            self.assertEqual(call.kwargs['port'], 1445)
            self.assertFalse(call.kwargs['follow_symlinks'])


if __name__ == '__main__':
    unittest.main()
