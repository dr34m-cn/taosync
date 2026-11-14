import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from service.alist.alistClient import AlistClient
from service.engine.taosyncClient import TaoSyncClient
from service.storage.drivers.smb import SmbDriver


class AlistFileListDetailTests(unittest.TestCase):
    @staticmethod
    def client():
        client = AlistClient.__new__(AlistClient)
        client.waits = {}
        return client

    def test_detail_api_adds_opaque_fingerprint_and_legacy_api_keeps_shape(self):
        response = {
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
        with patch.object(client, 'post', return_value=response):
            details = client.fileListDetailApi('/source/')
            legacy = client.fileListApi('/source/')

        self.assertEqual(legacy, {'folder/': {}, 'payload.bin': 4})
        self.assertEqual(details['payload.bin']['size'], 4)
        self.assertTrue(details['payload.bin']['fingerprint'].startswith('alist:sha256:'))
        self.assertNotIn('raw-backend-hash', details['payload.bin']['fingerprint'])


class TaoSyncFileListDetailTests(unittest.TestCase):
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
            stat=lambda follow_symlinks=False: info,
        )

        @contextmanager
        def scan_entries(*_args, **_kwargs):
            yield [entry]

        client = SimpleNamespace(scandir=scan_entries)
        driver = SmbDriver.__new__(SmbDriver)
        driver._client = lambda: client
        driver._remote = lambda path: path
        driver._assert_no_reparse = lambda *_args, **_kwargs: None
        driver._connection_kwargs = lambda: {}

        legacy = driver.list('/')
        detailed = driver.list('/', details=True)

        self.assertEqual(
            legacy, [{'name': 'payload.bin', 'is_dir': False, 'size': 4}]
        )
        self.assertTrue(detailed[0]['fingerprint'].startswith('smb:sha256:'))


if __name__ == '__main__':
    unittest.main()
