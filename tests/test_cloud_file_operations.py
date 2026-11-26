import io
import stat
import os
import tempfile
import threading
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch

from service.engine.taosyncClient import TaoSyncClient
from service.storage import storageService
from service.storage.drivers.aliyun import AliyunAPIError, AliyunDriveDriver
from service.storage.drivers.base import TransferCancelled
from service.storage.drivers.local import LocalDriver
from service.storage.drivers.smb import SmbDriver


def cloud():
    driver = AliyunDriveDriver({'client_id': 'client', 'client_secret': 'secret',
                               'refresh_token': 'refresh', 'drive_id': 'drive'})
    driver._ensure_drive = Mock()
    driver._request = Mock(return_value={'file_id': 'file'})
    driver._resolve = Mock(side_effect=lambda path, **kwargs: {
        'file_id': 'file' if path in ('/old.txt', '/folder') else 'parent' if path == '/' else 'destination',
        'parent_file_id': 'parent', 'type': 'file' if path == '/old.txt' else 'folder',
    })
    driver._list_id = Mock(return_value=[])
    driver.download = Mock(side_effect=AssertionError('cloud operation must not download'))
    driver.upload = Mock(side_effect=AssertionError('cloud operation must not upload'))
    driver._delete_id = Mock(side_effect=AssertionError('cloud operation must not delete'))
    driver._abort_upload = Mock(side_effect=AssertionError('cloud operation must not abort the source'))
    return driver


class CloudMoveTests(unittest.TestCase):
    def setUp(self):
        self.driver = cloud()
        self.addCleanup(self.driver.session.close)

    def test_rename_updates_the_existing_id_and_refuses_collisions(self):
        self.driver.rename('/old.txt', 'new.txt')
        self.driver._request.assert_called_once_with('/adrive/v1.0/openFile/update', {
            'drive_id': 'drive', 'file_id': 'file', 'name': 'new.txt', 'check_name_mode': 'refuse',
        })

    def test_move_calls_cloud_api_with_new_parent_and_name(self):
        self.driver.move('/old.txt', '/archive/new.txt')
        self.driver._request.assert_called_once_with('/adrive/v1.0/openFile/move', {
            'drive_id': 'drive', 'file_id': 'file', 'to_parent_file_id': 'destination',
            'new_name': 'new.txt', 'check_name_mode': 'refuse',
        })

    def test_folder_rename_is_native(self):
        self.driver.rename('/folder', 'renamed')
        self.assertTrue(self.driver._request.call_args.args[0].endswith('/update'))

    def test_conflicting_file_or_directory_is_never_removed(self):
        for kind in ('file', 'folder'):
            self.driver._list_id.return_value = [{'name': 'new.txt', 'file_id': 'other', 'type': kind}]
            with self.subTest(kind=kind), self.assertRaises(FileExistsError):
                self.driver.rename('/old.txt', 'new.txt')
        self.driver._request.assert_not_called()

    def test_invalid_names_and_mount_root_are_rejected(self):
        for name in ('', '/', '../file', 'bad\\name', 'bad\nname', '..'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.driver.rename('/old.txt', name)
        with self.assertRaises(ValueError):
            self.driver.move('/', '/archive/root')
        self.driver._request.assert_not_called()

    def test_cancel_before_request_preserves_source(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(TransferCancelled):
            self.driver.move('/old.txt', '/archive/old.txt', cancel=cancel)
        self.driver._request.assert_not_called()

    def test_late_cancel_does_not_rollback_a_committed_cloud_move(self):
        cancel = threading.Event()
        self.driver._request.side_effect = lambda *args: cancel.set() or {'file_id': 'file'}
        progress = []
        self.driver.move('/old.txt', '/archive/old.txt', cancel=cancel, progress=progress.append)
        self.assertEqual(progress, [1.0])
        self.driver._delete_id.assert_not_called()
        self.driver._abort_upload.assert_not_called()

    def test_cloud_error_leaves_source_and_conflicting_entries_intact(self):
        self.driver._request.side_effect = AliyunAPIError('conflict', 'AlreadyExist')
        with self.assertRaises(AliyunAPIError):
            self.driver.move('/old.txt', '/archive/old.txt')
        self.driver._delete_id.assert_not_called()
        self.driver._abort_upload.assert_not_called()

    def test_folder_cannot_move_into_itself_including_another_mount_alias(self):
        self.driver._resolve = AliyunDriveDriver._resolve.__get__(self.driver)
        self.driver.root_folder_id = 'root'
        self.driver._list_id.side_effect = lambda parent: {
            'root': [{'name': 'folder', 'type': 'folder', 'file_id': 'source'}],
            'source': [{'name': 'child', 'type': 'folder', 'file_id': 'child'}],
        }.get(parent, [])
        with self.assertRaisesRegex(ValueError, 'into itself'):
            self.driver.move('/folder', '/folder/child/folder')
        destination = cloud()
        self.addCleanup(destination.session.close)
        destination._resolve = AliyunDriveDriver._resolve.__get__(destination)
        destination.root_folder_id = 'source'
        with self.assertRaisesRegex(ValueError, 'into itself'):
            self.driver.move_to('/folder', destination, '/folder')
        self.driver._request.assert_not_called()

    def test_client_dispatches_moves_across_mounts_on_same_drive_without_copy_delete(self):
        destination = cloud()
        self.addCleanup(destination.session.close)
        mounts = [{'id': 1, 'name': 'Cloud', 'driverType': 'aliyun', 'config': {}},
                  {'id': 2, 'name': 'Archive', 'driverType': 'aliyun', 'config': {}}]
        with patch('service.engine.taosyncClient.storageMapper.getMountList', return_value=mounts), patch(
            'service.engine.taosyncClient.createDriver', side_effect=[self.driver, destination]
        ):
            client = TaoSyncClient(1)
        for path in ('/Cloud', '/Archive/archive'):
            client.fileListApi(path)
        task_id = client.relocateFile('/Cloud/old.txt', '/Archive/archive/new.txt')
        client.waitTask(task_id, 2)
        self.assertEqual(client.taskInfo(task_id)['state'], 2)
        self.assertNotIn('old.txt', client.fileListApi('/Cloud', useCache=1))
        self.assertIn('new.txt', client.fileListApi('/Archive/archive', useCache=1))
        self.assertTrue(self.driver._request.call_args.args[0].endswith('/move'))
        self.driver.download.assert_not_called()
        destination.upload.assert_not_called()
        self.driver._delete_id.assert_not_called()
        destination.drive_id = 'another-drive'
        with self.assertRaisesRegex(ValueError, 'same Aliyun drive'):
            client.relocateFile('/Cloud/old.txt', '/Archive/new.txt')
        with self.assertRaises(ValueError):
            client.renameFile('/Cloud', 'Renamed')

    def test_range_download_checks_content_range_and_closes_the_response(self):
        self.driver._request.return_value = {'url': 'https://example.test/download'}
        response = Mock(status_code=206, headers={'Content-Range': 'bytes 3-5/10'})
        response.iter_content.return_value = [b'345']
        self.driver.session.get = Mock(return_value=response)
        self.assertEqual(self.driver.read_range('/old.txt', 3, 3), b'345')
        response.close.assert_called_once()
        self.assertEqual(self.driver.session.get.call_args.kwargs['headers'], {'Range': 'bytes=3-5'})
        response.reset_mock()
        response.status_code = 200
        with self.assertRaisesRegex(IOError, 'byte range'):
            self.driver.read_range('/old.txt', 3, 3)
        response.close.assert_called_once()


class SourceMetadataTests(unittest.TestCase):
    def test_local_metadata_has_original_times_without_treating_unix_ctime_as_creation(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, 'file')
            with open(path, 'wb') as output:
                output.write(b'0123456789')
            os.utime(path, (1609459200, 1609459200))
            driver = LocalDriver({'root_path': root})
            metadata = driver.file_metadata('/file')
            self.assertEqual(metadata['modified_at'], 1609459200)
            if os.name == 'nt':
                self.assertEqual(metadata['created_at'], os.stat(path).st_ctime)
            self.assertEqual(driver.read_range('/file', 3, 3), b'345')

    def test_smb_metadata_and_range_use_the_smb_creation_time(self):
        driver = SmbDriver({'host': 'nas', 'share': 'files'})
        entry = Mock(name='file')
        entry.name = 'file'
        entry.is_dir.return_value = False
        entry.stat.return_value = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0,
                                                  st_size=10, st_ctime=1577836800, st_mtime=1609459200,
                                                  st_mtime_ns=1609459200000000000, st_ino=1)
        client = Mock()
        client.stat.return_value = entry.stat.return_value
        client.scandir.return_value = nullcontext([entry])
        client.open_file.return_value = nullcontext(io.BytesIO(b'0123456789'))
        with patch.object(driver, '_connection', side_effect=lambda: nullcontext()), patch.object(
            driver, '_client', return_value=client
        ), patch.object(driver, '_connection_kwargs', return_value={}), patch.object(
            driver, '_assert_no_reparse'
        ), patch.object(driver, '_entry_is_reparse', return_value=False):
            metadata = driver.file_metadata('/file')
            client.scandir.assert_not_called()
            self.assertEqual(metadata['created_at'], 1577836800)
            self.assertEqual(metadata['modified_at'], 1609459200)
            self.assertEqual(driver.read_range('/file', 4, 3), b'456')

    def test_cloud_metadata_uses_original_local_times_and_only_sha1_hashes(self):
        driver = cloud()
        self.addCleanup(driver.session.close)
        driver._resolve.return_value = {'file_id': 'root', 'type': 'folder'}
        driver._list_id.return_value = [
            {'name': 'file', 'type': 'file', 'file_id': 'file', 'size': 12,
             'local_created_at': '2020-01-01T00:00:00.000Z', 'created_at': '2026-01-01T00:00:00.000Z',
             'local_modified_at': '2021-01-01T00:00:00.000Z', 'updated_at': '2026-01-02T00:00:00.000Z',
             'content_hash': 'a' * 40, 'content_hash_name': 'sha1'},
            {'name': 'other', 'type': 'file', 'size': 1, 'content_hash': 'b' * 40, 'content_hash_name': 'crc64'},
        ]
        entries = driver.list('/', details=True)
        self.assertEqual(entries[0]['sha1'], 'A' * 40)
        self.assertEqual(entries[0]['created_at'], '2020-01-01T00:00:00.000Z')
        self.assertEqual(entries[0]['modified_at'], '2021-01-01T00:00:00.000Z')
        self.assertNotIn('sha1', entries[1])

    def test_source_hash_uses_the_same_duplicate_file_that_download_will_resolve(self):
        driver = cloud()
        self.addCleanup(driver.session.close)
        driver._resolve = AliyunDriveDriver._resolve.__get__(driver)
        driver._list_id.return_value = [
            {'name': 'file', 'file_id': 'old', 'type': 'file', 'size': 10,
             'updated_at': '2020-01-01T00:00:00Z', 'content_hash': 'a' * 40},
            {'name': 'file', 'file_id': 'new', 'type': 'file', 'size': 11,
             'updated_at': '2021-01-01T00:00:00Z', 'content_hash': 'b' * 40},
        ]
        metadata = driver.file_metadata('/file')
        self.assertEqual(metadata['size'], 11)
        self.assertEqual(metadata['sha1'], 'B' * 40)

    def test_hash_cache_requires_matching_source_fingerprint_and_size(self):
        driver = Mock()
        driver.file_metadata.return_value = {'size': 10, 'fingerprint': 'first', 'sha1': None}
        with patch('service.engine.taosyncClient.storageMapper.getMountList', return_value=[]):
            client = TaoSyncClient(1)
        mount = {'id': 1, 'driver': driver}
        client._rememberHash(mount, '/file', {'size': 10, 'fingerprint': 'first', 'sha1': 'A' * 40})
        self.assertEqual(client.fileMetadata(mount, '/file')['sha1'], 'A' * 40)
        driver.file_metadata.return_value = {'size': 10, 'fingerprint': 'changed'}
        self.assertNotIn('sha1', client.fileMetadata(mount, '/file'))
        driver.file_metadata.return_value = {'size': 11, 'fingerprint': 'first'}
        self.assertNotIn('sha1', client.fileMetadata(mount, '/file'))

    def test_file_operation_service_dispatches_only_after_engine_validation(self):
        client = Mock()
        client.renameFile.return_value = 'task'
        request = {'engineId': 1, 'action': 'fileRename', 'path': '/Cloud/file', 'name': 'new'}
        with patch.object(storageService, '_requireTaoSync') as require, patch(
            'service.engine.engineService.getClientById', return_value=client
        ):
            self.assertEqual(storageService.cloudFileOperation(request), {'taskId': 'task'})
            require.assert_called_once_with(1)
            client.renameFile.assert_called_once_with('/Cloud/file', 'new')

    def test_ui_poll_can_forget_terminal_tasks_but_keeps_running_tasks(self):
        client = Mock()
        with patch.object(storageService, '_requireTaoSync'), patch(
            'service.engine.engineService.getClientById', return_value=client
        ):
            for state in (1, 2, 4, 7):
                client.reset_mock()
                client.taskInfo.return_value = {'state': state, 'progress': 100}
                result = storageService.cloudFileOperation({
                    'engineId': 1, 'action': 'fileTask', 'taskId': 'task', 'forget': True,
                })
                self.assertEqual(result['state'], state)
                if state == 1:
                    client.copyTaskDelete.assert_not_called()
                else:
                    client.copyTaskDelete.assert_called_once_with('task')


if __name__ == '__main__':
    unittest.main()
