import threading
import unittest
from unittest.mock import Mock, patch

from service.engine.taosyncClient import TaoSyncClient
from service.storage.drivers.aliyun import AliyunAPIError, AliyunDriveDriver
from service.storage.drivers.base import StorageDriver
from service.storage.drivers.crypt import CryptDriver
from service.storage.drivers.scanState import ScanState
from service.syncJob.jobClient import JobTask


class Source(StorageDriver):
    def file_metadata(self, path):
        return {'size': 3}

    def download(self, path, target, progress=None, cancel=None):
        target.write(b'abc')


class ScannedUploadTests(unittest.TestCase):
    def test_comparable_hash_must_be_explicitly_identified_by_aliyun(self):
        raw = dict(name='sample', type='file', file_id='file', size=3, content_hash='A' * 40)
        for algorithm in (None, 'md5', 'sha1'):
            with self.subTest(algorithm=algorithm):
                item = dict(raw, content_hash_name=algorithm)
                self.entries['root'] = [item]
                for detail in (self.client.fileListDetailApi('/D/', useCache=0)['sample'],
                               self.client.fileDetail('/D/', 'sample')):
                    expected = {'sha1': 'a' * 40} if algorithm == 'sha1' else {}
                    self.assertEqual(detail.get('contentHashes', {}), expected)

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
                if data['parent_file_id'] not in self.entries:
                    raise AliyunAPIError('directory removed', 'NotFound.ParentFile')
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

    def scan_task(self, method=0):
        vm = Mock(job={'alistId': 1, 'method': method, 'useCacheS': 0, 'scanIntervalS': 0})
        with patch('service.syncJob.jobClient.engineService.getClientById', return_value=self.base), \
                patch('service.syncJob.jobClient.taskTimeoutSeconds', return_value=0):
            return JobTask(1, vm)

    def listed_ids(self):
        return [call.args[1]['parent_file_id'] for call in self.driver._request.call_args_list]

    def test_recursive_scan_lists_each_folder_once_and_keeps_verification_fresh(self):
        self.entries['parent'] = [dict(name='deep', type='folder', file_id='child')]
        self.entries['child'] = [dict(name='a', type='file', file_id='file', size=3)]
        task = self.scan_task()
        self.assertTrue(task.scanSourceTree('/D/', None, '/D/'))
        self.assertEqual(self.listed_ids(), ['root', 'parent', 'child'])
        self.assertEqual(task.sourceSnapshot['folder/deep/a']['size'], 3)

        task.listDir('/D/', True, None, '/D/')  # Offer a new, unconsumed hint for verification.
        self.entries['root'] = [dict(self.folder, file_id='replacement')]
        self.entries['replacement'] = []  # The old ID still exists elsewhere.
        self.driver._request.reset_mock()
        self.assertEqual(task.readDirectory('/D/folder/')[0], {})
        self.assertEqual(self.listed_ids(), ['root', 'replacement'])

    def test_paginated_parent_supplies_child_id_from_its_last_page(self):
        def request(endpoint, data):
            if data['parent_file_id'] == 'root' and not data['marker']:
                return {'items': [dict(name='a', type='file', file_id='file')], 'next_marker': 'page2'}
            return self.request(endpoint, data)

        self.driver._request.side_effect = request
        task = self.scan_task()
        self.assertTrue(task.scanSourceTree('/D/', None, '/D/'))
        self.assertEqual(self.listed_ids(), ['root', 'root', 'parent'])

    def test_stale_scan_id_re_resolves_path_once_and_records_replacement(self):
        task = self.scan_task()
        task.listDir('/D/', True, None, '/D/')
        self.entries['root'] = [dict(self.folder, file_id='replacement')]
        self.entries['replacement'] = [dict(name='new', type='file', file_id='new', size=1)]
        del self.entries['parent']
        self.driver._request.reset_mock()
        self.assertEqual(task.listDir('/D/folder/', True, None, '/D/'), {'new': 1})
        self.assertEqual(self.listed_ids(), ['parent', 'root', 'replacement'])
        self.assertEqual(task.alistClient.scan_states[2].get('/folder')[0]['file_id'], 'replacement')

    def test_scan_id_does_not_retry_rate_limit_as_missing_directory(self):
        task = self.scan_task()
        task.listDir('/D/', True, None, '/D/')
        self.driver._request.reset_mock()
        self.driver._request.side_effect = AliyunAPIError('rate limited', 'TooManyRequests')
        with self.assertRaisesRegex(AliyunAPIError, 'rate limited'):
            task.listDir('/D/folder/', True, None, '/D/', recordError=False)
        self.assertEqual(self.listed_ids(), ['parent'])

    def test_mirror_planning_observes_replacement_even_if_the_old_id_is_readable(self):
        task = self.scan_task(method=1)
        task.listDir('/D/', True, None, '/D/')
        self.entries['root'] = [dict(self.folder, file_id='replacement')]
        self.entries['replacement'] = [dict(name='keep', type='file', file_id='keep', size=1)]
        self.driver._request.reset_mock()
        self.assertEqual(task.listDir('/D/folder/', True, None, '/D/'), {'keep': 1})
        self.assertEqual(self.listed_ids(), ['root', 'replacement'])

    def test_scan_hint_cannot_direct_an_upload_into_a_moved_folder(self):
        task = self.scan_task()
        task.listDir('/D/', True, None, '/D/')
        self.entries['root'] = [dict(self.folder, name='moved'), dict(self.folder, file_id='replacement')]
        self.entries['replacement'] = []
        task.listDir('/D/folder/', True, None, '/D/')
        self.client = task.alistClient
        self.upload()
        self.assertEqual(self.entries['parent'], [])
        self.assertEqual([item['name'] for item in self.entries['replacement']], ['a'])

    def test_missing_scan_folder_is_not_recorded_as_empty(self):
        task = self.scan_task()
        task.listDir('/D/', True, None, '/D/')
        self.entries['root'] = []
        del self.entries['parent']
        with self.assertRaises(FileNotFoundError):
            task.listDir('/D/folder/', True, None, '/D/', recordError=False)
        self.assertTrue(task.sourceScanFailed)
        self.assertIsNone(task.alistClient.scan_states[2].get('/folder'))

    def test_ambiguous_invalidated_and_other_run_ids_are_not_used(self):
        for case in ('ambiguous', 'invalidated', 'new_run'):
            with self.subTest(case=case):
                self.entries['root'] = [self.folder]
                if case == 'ambiguous':
                    self.entries['root'].append(dict(self.folder, file_id='older'))
                task = self.scan_task()
                task.listDir('/D/', True, None, '/D/')
                if case == 'invalidated':
                    task.alistClient.scan_states[2].invalidate('/folder')
                elif case == 'new_run':
                    task = self.scan_task()
                self.entries['root'] = [dict(self.folder, file_id='replacement')]
                self.entries['replacement'] = []
                self.driver._request.reset_mock()
                task.listDir('/D/folder/', True, None, '/D/')
                self.assertEqual(self.listed_ids(), ['root', 'replacement'])

    def test_scan_reaches_copy_thread_and_new_files_need_only_create_complete(self):
        self.scan()
        task_id = self.upload()
        self.assertEqual(self.endpoints(), ['create', 'complete'])
        self.assertEqual(self.base.taskInfo(task_id)['state'], 2)
        self.assertIs(self.base.taskInfo(task_id)['rapidUpload'], False)
        state = self.client.scan_states[2].get('/folder')
        self.assertEqual(state[1][0]['file_id'], 'new-a')
        self.assertIsNone(self.driver.scan_state.get())

    def test_encrypted_batch_shares_one_listing_and_refuses_unseen_cloud_object(self):
        view = CryptDriver(self.driver, '/folder', 'test passphrase', False)
        self.client.mounts['C'] = dict(id=3, name='C', driverType='crypt',
                                       config={'target_mount_id': 2, 'target_path': '/folder'}, driver=view)
        def accept_part(url, data, **kwargs):
            self.assertEqual(len(data.read()), int(kwargs['headers']['Content-Length']))
            return Mock(status_code=200)
        self.driver.session.put.side_effect = accept_part
        for index in range(24):
            self.upload(name='long-' + str(index) + 'x' * 145, directory='/C')
        endpoints = self.endpoints()
        # Once to resolve /folder, once to load its contents. Each long name
        # needs exactly two new cloud objects (mapping and ciphertext).
        self.assertEqual(endpoints.count('list'), 2)
        self.assertEqual(endpoints.count('search'), 0)
        self.assertEqual((endpoints.count('create'), endpoints.count('complete')), (48, 48))
        physical, _ = view.cipher.storage_name('external')
        self.entries['parent'].append({'name': physical, 'file_id': 'outside', 'type': 'file', 'size': 5})
        self.driver._request.reset_mock()
        self.driver.session.put.reset_mock()
        task = self.client.copyFile('/S', '/C', 'external')
        self.client.waitTask(task, 5)
        for lang, fragment in [('en', 'already exists'), ('zh_CN', '同名')]:
            with patch('service.storage.localAccess.get_context_lang', return_value=lang):
                info = self.client.taskInfo(task)
                self.assertEqual(info['state'], 7)
                self.assertEqual(info['localError'], ('crypt_name_conflict',))
                self.assertIn(fragment, info['error'])
        self.assertEqual(self.endpoints(), ['create'])
        self.driver.session.put.assert_not_called()
        self.assertEqual(self.entries['parent'][-1]['file_id'], 'outside')
        self.assertIsNone(self.client.scan_states[2].get('/folder'))

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
        self.assertIs(other.listings, self.base.listings)

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

    def test_successful_copy_patches_shared_listing_without_exposing_cloud_ids(self):
        self.base.fileListApi('/D/folder')
        self.scan()
        self.upload()
        self.driver._request.reset_mock()
        self.assertEqual(self.base.fileListApi('/D/folder', useCache=1), {'a': 3})
        self.driver._request.assert_not_called()

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

    def test_stale_parent_still_refreshes_above_threshold_when_rapid_upload_is_off(self):
        self.driver.rapid_upload = False
        self.driver.rapid_upload_min_bytes = 0
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
        self.driver.rapid_upload_min_bytes = 0
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
