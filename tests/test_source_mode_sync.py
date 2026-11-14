import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from service.syncJob import jobClient, jobService


class FakeEngine:
    def __init__(self, listings, failCopies=None, fingerprints=None):
        self.listings = listings
        self.failCopies = set(failCopies or [])
        self.fingerprints = fingerprints or {}
        self.listCalls = []
        self.detailCalls = []
        self.copyCalls = []
        self.mkdirCalls = []
        self.deleteCalls = []
        self.deleteIntervals = []

    def fileListApi(self, path, useCache=0, scanInterval=0, spec=None, rootPath=None):
        self.listCalls.append(path)
        if path not in self.listings:
            raise FileNotFoundError(path)
        return dict(self.listings[path])

    def fileListDetailApi(self, path, useCache=0, scanInterval=0, spec=None, rootPath=None):
        self.listCalls.append(path)
        self.detailCalls.append((path, useCache, scanInterval))
        if path not in self.listings:
            raise FileNotFoundError(path)
        return {
            name: {
                'isDir': 1 if name.endswith('/') else 0,
                'size': None if name.endswith('/') else size,
                'fingerprint': self.fingerprints.get(path, {}).get(name),
            }
            for name, size in self.listings[path].items()
        }

    def copyFile(self, srcPath, dstPath, fileName):
        call = (srcPath, dstPath, fileName)
        self.copyCalls.append(call)
        if call in self.failCopies:
            raise RuntimeError('copy failed')
        return None

    def mkdir(self, path, scanInterval=0):
        self.mkdirCalls.append(path)

    def deleteFile(self, path, names, scanInterval=0):
        self.deleteCalls.append((path, tuple(names)))
        self.deleteIntervals.append(scanInterval)


def makeTask(engine, method=0, dstPath='/dst/', sourceMode=1):
    job = {
        'id': 42,
        'alistId': 1,
        'srcPath': '/src/',
        'dstPath': dstPath,
        'method': method,
        'sourceMode': sourceMode,
        'exclude': None,
        'useCacheS': 0,
        'scanIntervalS': 0,
        'useCacheT': 0,
        'scanIntervalT': 0,
        'minFileSize': None,
        'maxFileSize': None,
    }
    owner = SimpleNamespace(
        job=job, jobDoing=True, currentJobTask=None, finishRun=mock.Mock()
    )
    task = jobClient.JobTask.__new__(jobClient.JobTask)
    task.taskId = 99
    task.jobClient = owner
    task.job = job
    task.alistClient = engine
    task.createTime = time.time()
    task.finish = []
    task.doing = {}
    task.waiting = []
    task.lastWatching = 0.0
    task.queueNum = 0
    task.scanFinish = False
    task.firstSync = None
    task.breakFlag = False
    task.sourceSnapshot = {}
    task.sourceScanAttempted = False
    task.sourceScanFailed = False
    task.currentTasks = {}
    owner.currentJobTask = task
    return task


class SourceModeSyncTest(unittest.TestCase):
    def runTask(self, task, storedSnapshot):
        with mock.patch.object(jobClient.jobMapper, 'getSourceSnapshot', return_value=storedSnapshot), \
                mock.patch.object(jobClient.jobMapper, 'replaceSourceSnapshot') as replaceSnapshot, \
                mock.patch.object(jobClient.jobMapper, 'addJobTaskItemMany'), \
                mock.patch.object(jobClient.taskService, 'updateJobTaskStatus'), \
                mock.patch.object(jobClient.CopyItem, 'doByThread', jobClient.CopyItem.doIt), \
                mock.patch.object(jobClient.time, 'sleep', return_value=None):
            task.sync()
            task.taskSubmit()
        return replaceSnapshot

    @staticmethod
    def initialized(entries):
        return {
            'meta': {'jobId': 42, 'initialized': 1, 'scanTime': 1, 'entryCount': len(entries)},
            'entries': entries,
        }

    def test_subsequent_add_mode_scans_only_source_and_copies_diff_to_every_target(self):
        engine = FakeEngine({
            '/src/': {'same.txt': 1, 'new.txt': 2, 'folder/': {}},
            '/src/folder/': {'changed.bin': 3},
        })
        task = makeTask(engine, dstPath='/dst-a/:/dst-b/')
        stored = self.initialized([
            {'path': 'same.txt', 'isDir': 0, 'size': 1},
            {'path': 'folder', 'isDir': 1, 'size': None},
            {'path': 'folder/changed.bin', 'isDir': 0, 'size': 2},
        ])

        replaceSnapshot = self.runTask(task, stored)

        self.assertEqual(engine.listCalls, ['/src/', '/src/folder/'])
        self.assertNotIn('/dst-a/', engine.listCalls)
        self.assertCountEqual(engine.copyCalls, [
            ('/src/', '/dst-a/', 'new.txt'),
            ('/src/folder/', '/dst-a/folder/', 'changed.bin'),
            ('/src/', '/dst-b/', 'new.txt'),
            ('/src/folder/', '/dst-b/folder/', 'changed.bin'),
        ])
        replaceSnapshot.assert_called_once()
        committed = replaceSnapshot.call_args.args[1]
        self.assertEqual({item['path'] for item in committed},
                         {'same.txt', 'new.txt', 'folder', 'folder/changed.bin'})

    def test_same_size_fingerprint_change_is_copied_without_target_scan(self):
        engine = FakeEngine(
            {'/src/': {'same-size.txt': 4}},
            fingerprints={'/src/': {'same-size.txt': 'version:new'}},
        )
        task = makeTask(engine)
        stored = self.initialized([
            {
                'path': 'same-size.txt',
                'isDir': 0,
                'size': 4,
                'fingerprint': 'version:old',
            },
        ])

        self.runTask(task, stored)

        self.assertEqual(engine.copyCalls, [('/src/', '/dst/', 'same-size.txt')])
        self.assertNotIn('/dst/', engine.listCalls)

    def test_full_mode_applies_tracked_removals_without_target_scan(self):
        engine = FakeEngine({'/src/': {}})
        task = makeTask(engine, method=1, dstPath='/dst-a/:/dst-b/')
        stored = self.initialized([
            {'path': 'gone.txt', 'isDir': 0, 'size': 5},
            {'path': 'gone-dir', 'isDir': 1, 'size': None},
            {'path': 'gone-dir/child.txt', 'isDir': 0, 'size': 6},
        ])

        self.runTask(task, stored)

        self.assertEqual(engine.listCalls, ['/src/'])
        self.assertCountEqual(engine.deleteCalls, [
            ('/dst-a/', ('gone.txt',)),
            ('/dst-a/gone-dir/', ('child.txt',)),
            ('/dst-b/', ('gone.txt',)),
            ('/dst-b/gone-dir/', ('child.txt',)),
        ])

    def test_failed_copy_does_not_advance_snapshot(self):
        failedCall = ('/src/', '/dst-b/', 'new.txt')
        engine = FakeEngine({'/src/': {'new.txt': 2}}, failCopies={failedCall})
        task = makeTask(engine, dstPath='/dst-a/:/dst-b/')

        replaceSnapshot = self.runTask(task, self.initialized([]))

        replaceSnapshot.assert_not_called()
        self.assertTrue(any(item['status'] == 7 for item in task.finish))

    def test_incomplete_source_scan_does_not_advance_snapshot(self):
        engine = FakeEngine({'/src/': {'missing/': {}}})
        task = makeTask(engine)

        replaceSnapshot = self.runTask(task, self.initialized([]))

        self.assertEqual(engine.listCalls, ['/src/', '/src/missing/'])
        replaceSnapshot.assert_not_called()
        self.assertTrue(task.sourceScanFailed)

    def test_move_copies_all_targets_then_deletes_source_once(self):
        engine = FakeEngine(
            {'/src/': {'move.txt': 7}},
            fingerprints={'/src/': {'move.txt': 'version:stable'}},
        )
        task = makeTask(engine, method=2, dstPath='/dst-a/:/dst-b/')

        replaceSnapshot = self.runTask(task, self.initialized([]))

        self.assertCountEqual(engine.copyCalls, [
            ('/src/', '/dst-a/', 'move.txt'),
            ('/src/', '/dst-b/', 'move.txt'),
        ])
        self.assertEqual(engine.deleteCalls, [('/src/', ('move.txt',))])
        replaceSnapshot.assert_called_once()
        self.assertEqual(replaceSnapshot.call_args.args, (42, []))

    def test_move_keeps_source_when_any_target_copy_fails(self):
        failedCall = ('/src/', '/dst-b/', 'move.txt')
        engine = FakeEngine({'/src/': {'move.txt': 7}}, failCopies={failedCall})
        task = makeTask(engine, method=2, dstPath='/dst-a/:/dst-b/')

        replaceSnapshot = self.runTask(task, self.initialized([]))

        self.assertEqual(engine.deleteCalls, [])
        replaceSnapshot.assert_not_called()

    def test_move_keeps_source_when_file_changes_after_copy(self):
        class ReplacingEngine(FakeEngine):
            def copyFile(innerSelf, srcPath, dstPath, fileName):
                result = super(ReplacingEngine, innerSelf).copyFile(srcPath, dstPath, fileName)
                innerSelf.listings['/src/']['move.txt'] = 8
                return result

        engine = ReplacingEngine({'/src/': {'move.txt': 7}})
        task = makeTask(engine, method=2)

        replaceSnapshot = self.runTask(task, self.initialized([]))

        self.assertEqual(engine.deleteCalls, [])
        replaceSnapshot.assert_not_called()
        self.assertTrue(any(item['status'] == 7 for item in task.finish))

    def test_move_keeps_same_size_replacement_when_fingerprint_changes(self):
        class ReplacingEngine(FakeEngine):
            def copyFile(innerSelf, srcPath, dstPath, fileName):
                result = super(ReplacingEngine, innerSelf).copyFile(srcPath, dstPath, fileName)
                innerSelf.fingerprints['/src/']['move.txt'] = 'version:replacement'
                return result

        engine = ReplacingEngine(
            {'/src/': {'move.txt': 7}},
            fingerprints={'/src/': {'move.txt': 'version:scanned'}},
        )
        task = makeTask(engine, method=2)

        replaceSnapshot = self.runTask(task, self.initialized([]))

        self.assertEqual(engine.deleteCalls, [])
        replaceSnapshot.assert_not_called()
        self.assertTrue(any(item['status'] == 7 for item in task.finish))

    def test_move_keeps_source_when_backend_has_no_version_marker(self):
        engine = FakeEngine({'/src/': {'move.txt': 7}})
        task = makeTask(engine, method=2)

        replaceSnapshot = self.runTask(task, self.initialized([]))

        self.assertEqual(engine.copyCalls, [('/src/', '/dst/', 'move.txt')])
        self.assertEqual(engine.deleteCalls, [])
        replaceSnapshot.assert_not_called()
        self.assertTrue(any(item['status'] == 7 for item in task.finish))

    def test_move_rechecks_without_delay_and_deletes_without_second_wait(self):
        engine = FakeEngine(
            {'/src/': {'move.txt': 7}},
            fingerprints={'/src/': {'move.txt': 'version:stable'}},
        )
        task = makeTask(engine, method=2)
        task.job['scanIntervalS'] = 30

        self.runTask(task, self.initialized([]))

        self.assertEqual(engine.deleteCalls, [('/src/', ('move.txt',))])
        self.assertEqual(engine.deleteIntervals, [0])
        self.assertEqual(engine.detailCalls[-1], ('/src/', 0, 0))

    def test_move_requires_one_unique_success_record_for_every_destination(self):
        for dstPath, delivered in (
            ('/dst-a/:/dst-b/', ['/dst-a/']),
            ('/dst-a/', ['/dst-a/', '/dst-a/']),
        ):
            with self.subTest(dstPath=dstPath, delivered=delivered):
                engine = FakeEngine({'/src/': {'move.txt': 7}})
                task = makeTask(engine, method=2, dstPath=dstPath)
                task.sourceScanAttempted = True
                task.sourceSnapshot = {
                    'move.txt': {'path': 'move.txt', 'isDir': 0, 'size': 7}
                }
                task.finish = [
                    {
                        'taskId': 99,
                        'srcPath': '/src/',
                        'dstPath': destination,
                        'isPath': 0,
                        'fileName': 'move.txt',
                        'fileSize': 7,
                        'type': 2,
                        'alistTaskId': None,
                        'status': 2,
                        'errMsg': None,
                        'createTime': 1,
                    }
                    for destination in delivered
                ]

                task.finalizeMove()

                self.assertEqual(engine.deleteCalls, [])
                self.assertTrue(any(item['status'] == 7 for item in task.finish))

    def test_normal_move_overwrites_same_size_target_before_deleting_source(self):
        engine = FakeEngine(
            {
                '/src/': {'payload.bin': 4},
                '/dst/': {'payload.bin': 4},
            },
            fingerprints={'/src/': {'payload.bin': 'version:stable'}},
        )
        task = makeTask(engine, method=2, sourceMode=0)
        stored = {
            'meta': {'jobId': 42, 'initialized': 0, 'scanTime': None, 'entryCount': 0},
            'entries': [],
        }

        self.runTask(task, stored)

        self.assertEqual(engine.copyCalls, [('/src/', '/dst/', 'payload.bin')])
        self.assertEqual(engine.deleteCalls, [('/src/', ('payload.bin',))])

    def test_uninitialized_source_mode_still_scans_target(self):
        engine = FakeEngine({
            '/src/': {'new.txt': 2},
            '/dst/': {},
        })
        task = makeTask(engine)
        stored = {
            'meta': {'jobId': 42, 'initialized': 0, 'scanTime': None, 'entryCount': 0},
            'entries': [],
        }

        replaceSnapshot = self.runTask(task, stored)

        self.assertEqual(engine.listCalls, ['/src/', '/dst/'])
        self.assertEqual(engine.copyCalls, [('/src/', '/dst/', 'new.txt')])
        replaceSnapshot.assert_called_once()

    def test_disabled_source_mode_still_records_successful_source_scan(self):
        engine = FakeEngine({
            '/src/': {'same.txt': 2},
            '/dst/': {'same.txt': 2},
        })
        task = makeTask(engine, sourceMode=0)

        replaceSnapshot = self.runTask(task, self.initialized([]))

        self.assertEqual(engine.listCalls, ['/src/', '/dst/'])
        self.assertEqual(engine.copyCalls, [])
        replaceSnapshot.assert_called_once()
        self.assertEqual(replaceSnapshot.call_args.args[1], [
            {'path': 'same.txt', 'isDir': 0, 'size': 2}
        ])

    def test_disabled_source_mode_delivers_same_size_fingerprint_change(self):
        engine = FakeEngine(
            {
                '/src/': {'same.txt': 2},
                '/dst/': {'same.txt': 2},
            },
            fingerprints={'/src/': {'same.txt': 'version:new'}},
        )
        task = makeTask(engine, sourceMode=0)
        stored = self.initialized([
            {
                'path': 'same.txt',
                'isDir': 0,
                'size': 2,
                'fingerprint': 'version:old',
            }
        ])

        self.runTask(task, stored)

        self.assertEqual(engine.copyCalls, [('/src/', '/dst/', 'same.txt')])

    def test_overlapping_paths_fail_before_any_scan_or_move_delete(self):
        engine = FakeEngine({'/src/': {'only.txt': 2}})
        task = makeTask(engine, method=2, dstPath='/src/')

        replaceSnapshot = self.runTask(task, self.initialized([]))

        self.assertEqual(engine.listCalls, [])
        self.assertEqual(engine.copyCalls, [])
        self.assertEqual(engine.deleteCalls, [])
        replaceSnapshot.assert_not_called()


class SourceModeInputTest(unittest.TestCase):
    @staticmethod
    def job(sourceMode='missing'):
        value = {
            'enable': 1,
            'isCron': 2,
            'exclude': None,
            'minFileSize': None,
            'maxFileSize': None,
        }
        if sourceMode != 'missing':
            value['sourceMode'] = sourceMode
        return value

    def test_legacy_input_defaults_to_disabled_and_binary_values_are_normalized(self):
        legacy = self.job()
        enabled = self.job(' 1 ')

        jobService.cleanJobInput(legacy)
        jobService.cleanJobInput(enabled)

        self.assertEqual(legacy['sourceMode'], 0)
        self.assertEqual(enabled['sourceMode'], 1)

    def test_invalid_source_mode_is_rejected(self):
        with self.assertRaises(Exception):
            jobService.cleanJobInput(self.job(2))

    def test_overlapping_source_and_destination_are_rejected(self):
        value = self.job(0)
        value.update({
            'srcPath': '/storage/source/',
            'dstPath': '/storage/source/backup/',
            'method': 0,
        })
        with self.assertRaises(Exception):
            jobService.cleanJobInput(value)

        caseAlias = self.job(0)
        caseAlias.update({
            'srcPath': '/Local/Data/',
            'dstPath': '/local/data/',
            'method': 2,
        })
        with self.assertRaises(Exception):
            jobService.cleanJobInput(caseAlias)


class SourceModeEditTest(unittest.TestCase):
    @staticmethod
    def completeJob():
        return {
            'id': 8,
            'enable': 0,
            'isCron': 0,
            'alistId': 1,
            'srcPath': '/src/',
            'dstPath': '/dst/',
            'method': 0,
            'exclude': None,
            'minFileSize': None,
            'maxFileSize': None,
            'sourceMode': 0,
        }

    def runEdit(self, oldJob, newJob, updateSideEffect=None):
        oldClient = SimpleNamespace(job=oldJob, stopJob=mock.Mock())
        newClient = SimpleNamespace(jobId=8, stopJob=mock.Mock())
        restoredClient = SimpleNamespace(jobId=8, stopJob=mock.Mock())
        originalClients = jobService.jobClientList
        jobService.jobClientList = {8: oldClient}
        try:
            with mock.patch.object(jobService, 'getJobClientById', return_value=oldClient), \
                    mock.patch.object(jobService.jobClient, 'JobClient', side_effect=[newClient, restoredClient]) as clientFactory, \
                    mock.patch.object(jobService.jobMapper, 'updateJob', side_effect=updateSideEffect) as updateJob:
                if updateSideEffect is None:
                    jobService.editJobClient(newJob)
                else:
                    with self.assertRaises(Exception):
                        jobService.editJobClient(newJob)
                return oldClient, newClient, restoredClient, clientFactory, updateJob, jobService.jobClientList.get(8)
        finally:
            jobService.jobClientList = originalClients

    def test_switch_only_edit_keeps_snapshot(self):
        oldJob = self.completeJob()
        newJob = {**oldJob, 'sourceMode': 1}

        _old, _new, _restored, _factory, updateJob, registered = self.runEdit(oldJob, newJob)

        updateJob.assert_called_once_with(newJob, clearSourceSnapshot=False)
        self.assertIsNotNone(registered)

    def test_source_identity_edit_invalidates_snapshot(self):
        oldJob = self.completeJob()
        newJob = {**oldJob, 'srcPath': '/new-source/'}

        _old, _new, _restored, _factory, updateJob, _registered = self.runEdit(oldJob, newJob)

        updateJob.assert_called_once_with(newJob, clearSourceSnapshot=True)

    def test_failed_update_stops_new_client_and_restores_old_configuration(self):
        oldJob = self.completeJob()
        newJob = {**oldJob, 'dstPath': '/new-target/'}

        oldClient, newClient, restoredClient, clientFactory, _update, registered = self.runEdit(
            oldJob, newJob, updateSideEffect=RuntimeError('database failed')
        )

        oldClient.stopJob.assert_called_once_with(remove=True)
        newClient.stopJob.assert_called_once_with(remove=True)
        self.assertEqual(clientFactory.call_args_list[1].args[0], oldJob)
        self.assertIs(registered, restoredClient)


class JobRunLockTest(unittest.TestCase):
    def test_concurrent_trigger_cannot_start_a_second_task(self):
        client = jobClient.JobClient.__new__(jobClient.JobClient)
        client.jobId = 5
        client.job = {'enable': 1}
        client.runLock = threading.Lock()
        client.jobDoing = False
        client.currentJobTask = None

        fakeTask = SimpleNamespace(start=mock.Mock())
        with mock.patch.object(jobClient.jobMapper, 'addJobTask', return_value=10) as addTask, \
                mock.patch.object(jobClient, 'JobTask', return_value=fakeTask):
            client.doJob()
            client.doJob()

        addTask.assert_called_once()
        fakeTask.start.assert_called_once()
        self.assertTrue(client.runLock.locked())
        client.finishRun()
        self.assertFalse(client.runLock.locked())


if __name__ == '__main__':
    unittest.main()
