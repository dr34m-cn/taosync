import threading
import unittest
from unittest.mock import Mock, patch

from service.engine.taosyncClient import TaoSyncClient
from service.storage.drivers.aliyun import AliyunAPIError, AliyunDriveDriver
from service.storage.drivers.base import StorageDriver
from service.storage.drivers.scanState import ScanState
from service.syncJob.jobClient import JobTask


class Source(StorageDriver):
    def file_metadata(self, path):
        return {'size': 3}

    def download(self, path, target, progress=None, cancel=None):
        target.write(b'abc')


class ScannedUploadTests(unittest.TestCase):
    def setUp(self):
        self.driver = AliyunDriveDriver({
            'client_id': 'client', 'client_secret': 'secret',
            'refresh_token': 'refresh', 'drive_id': 'drive',
        })
        self.addCleanup(self.driver.session.close)
        self.folder = {'name': 'folder', 'file_id': 'parent', 'type': 'folder'}
        self.entries = {'root': [self.folder], 'parent': []}
        self.pending = {}
        self.api_lock = threading.Lock()
        self.driver._request = Mock(side_effect=self.request)
        self.driver.session.put = Mock(side_effect=self.put)
        rows = [dict(id=1, name='S', driverType='local', config={}),
                dict(id=2, name='D', driverType='aliyun', config={})]
        with patch('service.engine.taosyncClient.storageMapper.getMountList', return_value=rows), \
                patch('service.engine.taosyncClient.createDriver', side_effect=[Source(), self.driver]):
            self.base = TaoSyncClient(1)
        self.client = self.base.forSync()

    def request(self, endpoint, data):
        with self.api_lock:
            if endpoint.endswith('/list'):
                return {'items': list(self.entries[data['parent_file_id']])}
            if endpoint.endswith('/search'):
                parent, name = data['query'].split("'")[1::2]
                return {'items': [item for item in self.entries[parent] if item['name'] == name]}
            if endpoint.endswith('/create'):
                parent = data['parent_file_id']
                if parent not in self.entries:
                    raise AliyunAPIError('parent missing', 'NotFound.ParentFile')
                matches = [item for item in self.entries[parent] if item['name'] == data['name']]
                if data['check_name_mode'] == 'refuse' and matches:
                    return dict(matches[0], exist=True)
                item = {'file_id': 'new-' + data['name'], 'name': data['name'],
                        'type': data['type'], 'size': data.get('size', 0)}
                if data['type'] == 'folder':
                    self.entries[parent].append(item)
                    self.entries[item['file_id']] = []
                    return item
                self.pending[item['file_id']] = (parent, item)
                return dict(item, upload_id='upload', part_info_list=[
                    {'part_number': 1, 'upload_url': 'https://example.test/part'}])
            if endpoint.endswith('/complete'):
                parent, item = self.pending.pop(data['file_id'])
                self.entries[parent].append(item)
                return item
            if endpoint.endswith('/trash') or endpoint.endswith('/delete'):
                for entries in self.entries.values():
                    entries[:] = [item for item in entries if item['file_id'] != data['file_id']]
                return {}
            raise AssertionError(endpoint)

    def put(self, url, data, **kwargs):
        self.assertEqual(data.read(), b'abc')
        return Mock(status_code=200)

    def scan(self):
        self.client.fileListApi('/D/folder')
        self.driver._request.reset_mock()

    def upload(self, name='a', directory='/D/folder'):
        task_id = self.client.copyFile('/S', directory, name)
        self.client.waitTask(task_id, 5)
        info = self.client.taskInfo(task_id)
        self.assertEqual(info['state'], 2, info['error'])
        return task_id

    def endpoints(self):
        return [call.args[0].rsplit('/', 1)[-1] for call in self.driver._request.call_args_list]

    def test_scan_reaches_copy_thread_and_new_files_need_only_create_complete(self):
        self.scan()
        task_id = self.upload()
        self.assertEqual(self.endpoints(), ['create', 'complete'])
        self.assertEqual(self.base.taskInfo(task_id)['state'], 2)
        self.assertIs(self.base.taskInfo(task_id)['rapidUpload'], False)
        state = self.client.scan_states[2].get('/folder')
        self.assertEqual(state[1][0]['file_id'], 'new-a')
        self.assertIsNone(self.driver.scan_state.get())

    def test_parallel_copies_share_scan_but_keep_all_completed_entries(self):
        self.scan()
        tasks = [self.client.copyFile('/S', '/D/folder', str(index)) for index in range(8)]
        for task in tasks:
            self.client.waitTask(task, 5)
            self.assertEqual(self.client.taskInfo(task)['state'], 2)
        self.assertEqual(len(self.endpoints()), 16)
        self.assertEqual(set(self.endpoints()), {'create', 'complete'})
        self.assertEqual(len(self.client.scan_states[2].get('/folder')[1]), 8)

    def test_new_run_has_no_scan_state_from_previous_run(self):
        self.scan()
        other = self.base.forSync()
        self.assertIsNone(other.scan_states[2].get('/folder'))
        self.assertEqual(other.entry_cache, {})

    def test_job_queue_uses_the_same_scoped_client_as_scanning(self):
        vm = Mock(job={'alistId': 1, 'method': 0})
        with patch('service.syncJob.jobClient.engineService.getClientById', return_value=self.base), \
                patch('service.syncJob.jobClient.taskTimeoutSeconds', return_value=0), \
                patch('service.syncJob.jobClient.jobMapper.sourceSnapshotIdentity', return_value={}):
            task = JobTask(1, vm)
        self.assertIsNot(task.alistClient, self.base)
        task.alistClient.fileListApi('/D/folder')
        task.copyFile('/S', '/D/folder', 'a', 3)
        self.assertIs(task.waiting[0].alistClient, task.alistClient)
        self.assertIsNotNone(task.waiting[0].alistClient.scan_states[2].get('/folder'))

    def test_successful_copy_invalidates_shared_browser_cache(self):
        self.base.fileListApi('/D/folder')
        self.scan()
        self.upload()
        self.assertNotIn((2, '/folder'), self.base.entry_cache)

    def test_new_directory_immediately_supports_query_free_upload(self):
        self.client.fileListApi('/D')
        self.client.mkdir('/D/newdir')
        self.driver._request.reset_mock()
        self.upload(directory='/D/newdir')
        self.assertEqual(self.endpoints(), ['create', 'complete'])

    def test_conflicting_folder_after_scan_is_not_uploaded_or_deleted(self):
        self.scan()
        self.entries['parent'].append({'name': 'a', 'file_id': 'external-folder', 'type': 'folder'})
        task = self.client.copyFile('/S', '/D/folder', 'a')
        self.client.waitTask(task, 5)
        self.assertEqual(self.client.taskInfo(task)['state'], 7)
        self.driver.session.put.assert_not_called()
        self.assertNotIn('delete', self.endpoints())
        self.assertNotIn('trash', self.endpoints())
        self.assertIsNone(self.client.scan_states[2].get('/folder'))

    def test_stale_parent_refreshes_before_reading_source(self):
        self.scan()
        self.entries['replacement'] = self.entries.pop('parent')
        self.entries['root'] = [dict(self.folder, file_id='replacement')]
        self.upload()
        creates = [call.args[1] for call in self.driver._request.call_args_list if call.args[0].endswith('/create')]
        self.assertEqual([item['parent_file_id'] for item in creates], ['parent', 'replacement'])
        self.driver.session.put.assert_called_once()

    def test_overwrite_keeps_old_file_until_complete_and_checks_conflicts(self):
        old = {'name': 'a', 'file_id': 'old', 'type': 'file', 'size': 1}
        self.entries['parent'].append(old)
        self.scan()
        original = self.put

        def put(*args, **kwargs):
            self.assertIn(old, self.entries['parent'])
            return original(*args, **kwargs)

        self.driver.session.put.side_effect = put
        self.upload()
        self.assertEqual(self.endpoints(), ['create', 'complete', 'search', 'trash'])
        self.assertEqual([item['file_id'] for item in self.entries['parent']], ['new-a'])

    def test_failed_complete_preserves_old_file_and_invalidates_scan(self):
        old = {'name': 'a', 'file_id': 'old', 'type': 'file', 'size': 1}
        self.entries['parent'].append(old)
        self.scan()

        def request(endpoint, data):
            if endpoint.endswith('/complete'):
                raise AliyunAPIError('complete failed', 'Error')
            return self.request(endpoint, data)

        self.driver._request.side_effect = request
        task = self.client.copyFile('/S', '/D/folder', 'a')
        self.client.waitTask(task, 5)
        self.assertEqual(self.client.taskInfo(task)['state'], 7)
        self.assertIn(old, self.entries['parent'])
        self.assertIsNone(self.client.scan_states[2].get('/folder'))

    def test_rapid_commit_updates_scan_without_complete_or_duplicate_query(self):
        self.scan()
        self.driver.RAPID_UPLOAD_THRESHOLD = 1
        source = Source()
        source.supports_random_read = True
        source.file_metadata = Mock(return_value={'size': 3, 'sha1': 'A' * 40})
        source.read_range = Mock(return_value=b'abc')
        self.client.mounts['S'] = dict(self.client.mounts['S'], driver=source)
        self.driver._request.side_effect = lambda endpoint, data: {
            'file_id': 'rapid-a', 'rapid_upload': True}
        # A poll between driver commit and engine success must not see ordinary transferred bytes.
        def check_before_finish(*_):
            self.assertEqual(self.client.copyTaskUnDone()[0]['progress'], 0)

        with patch.object(self.client, '_rememberHash', side_effect=check_before_finish):
            task_id = self.upload()
        self.assertIs(self.client.taskInfo(task_id)['rapidUpload'], True)
        self.assertEqual(self.endpoints(), ['create'])
        self.driver.session.put.assert_not_called()
        self.assertEqual(self.client.scan_states[2].lookup('/folder', 'a')[1][0]['file_id'], 'rapid-a')

    def test_delete_updates_scan_for_subsequent_new_upload(self):
        self.entries['parent'].append({'name': 'a', 'file_id': 'old', 'type': 'file'})
        self.scan()
        self.client.deleteFile('/D/folder', ['a'])
        self.driver._request.reset_mock()
        self.upload()
        self.assertEqual(self.endpoints(), ['create', 'complete'])

    def test_source_only_run_loads_directory_once_for_following_uploads(self):
        self.upload()
        self.driver._request.reset_mock()
        self.upload('b')
        self.assertEqual(self.endpoints(), ['create', 'complete'])


class ScanStateTests(unittest.TestCase):
    def test_late_listing_cannot_erase_concurrent_completed_upload(self):
        state = ScanState()
        parent = {'file_id': 'parent'}
        state.record('/folder', parent, [])
        revision = state.revision
        state.put('/folder/new', {'file_id': 'new', 'type': 'file'})
        state.record('/folder', parent, [], revision)
        self.assertEqual(state.get('/folder')[1][0]['file_id'], 'new')

    def test_deleting_directory_invalidates_descendant_records(self):
        state = ScanState()
        state.record('/folder', {'file_id': 'parent'}, [])
        state.record('/folder/child', {'file_id': 'child'}, [])
        state.remove('/folder')
        self.assertIsNone(state.get('/folder/child'))
