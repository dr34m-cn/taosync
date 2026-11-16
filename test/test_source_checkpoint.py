"""Durable per-file progress, including interrupted and multi-target runs."""
import sqlite3
from contextlib import closing
from unittest import mock

from common import config
from mapper import jobMapper
from service.engine import engineService
from service.syncJob.jobClient import JobTask
from service.syncJob import jobService
from test_builtin_engine_sync import EngineTestBase, write


class SourceCheckpointTest(EngineTestBase):
    def interrupt_after_file(self, jobId, name):
        original = JobTask.checkpointSourceFile
        observed = []

        def checkpoint(task, src, dst, filename):
            original(task, src, dst, filename)
            if (src + filename)[len(task.normalizeRoot(task.job['srcPath'])):] == name:
                saved = jobMapper.getSourceSnapshot(jobId)
                if any(e['path'] == name and e.get('fingerprint') == task.sourceSnapshot[name].get('fingerprint')
                       for e in saved['entries']):
                    observed.append(saved)
                    task.breakFlag = True

        with mock.patch.object(JobTask, 'checkpointSourceFile', checkpoint):
            self._run(jobId)
        self.assertTrue(observed, 'file must be visible to another DB connection before task completion')
        return observed[-1]

    def test_incremental_abort_keeps_completed_fingerprint(self):
        write(self.src, 'a', b'old')
        jobId = self._job(sourceMode=1)
        self._run(jobId)
        before = jobMapper.getSourceSnapshot(jobId)['meta']['fullScanTime']
        write(self.src, 'a', b'new')
        saved = self.interrupt_after_file(jobId, 'a')
        self.assertEqual(saved['meta']['fullScanTime'], before)
        with mock.patch.object(JobTask, 'copyFile', autospec=True) as copy:
            self._run(jobId)
        copy.assert_not_called()

    def test_initial_abort_keeps_scan_uninitialized_but_file_durable(self):
        write(self.src, 'a', b'new')
        jobId = self._job(sourceMode=1)
        saved = self.interrupt_after_file(jobId, 'a')
        self.assertEqual(saved['meta']['initialized'], 0)
        self.assertIsNone(saved['meta']['fullScanTime'])
        with mock.patch.object(JobTask, 'copyFile', autospec=True) as copy:
            self._run(jobId)
        copy.assert_not_called()
        self.assertEqual(jobMapper.getSourceSnapshot(jobId)['meta']['initialized'], 1)

    def test_failed_file_keeps_old_version_and_is_retried(self):
        write(self.src, 'a', b'old')
        write(self.src, 'b', b'old')
        jobId = self._job(sourceMode=1)
        self._run(jobId)
        old = {e['path']: e for e in jobMapper.getSourceSnapshot(jobId)['entries']}
        write(self.src, 'a', b'new')
        write(self.src, 'b', b'new')
        engine = engineService.getClientById(self.engineId)
        original = engine.copyFile

        def fail(src, dst, name):
            if name == 'b':
                raise OSError('injected copy failure')
            return original(src, dst, name)

        with mock.patch.object(engine, 'copyFile', side_effect=fail):
            self._run(jobId)
        saved = {e['path']: e for e in jobMapper.getSourceSnapshot(jobId)['entries']}
        self.assertNotEqual(saved['a'], old['a'])
        self.assertEqual(saved['b'], old['b'])
        with mock.patch.object(engine, 'copyFile', wraps=original) as copies:
            self._run(jobId)
        self.assertEqual([c.args[2] for c in copies.call_args_list], ['b'])

    def test_multiple_targets_only_checkpoint_after_all_succeed(self):
        write(self.src, 'a', b'old')
        second = self._dir('second')
        self._mount('E', second)
        jobId = self._job(sourceMode=1, dst='/D/:/E/')
        self._run(jobId)
        old = jobMapper.getSourceSnapshot(jobId)['entries']
        write(self.src, 'a', b'new')
        engine = engineService.getClientById(self.engineId)
        original = engine.copyFile

        def fail(src, dst, name):
            if dst == '/E/':
                raise OSError('second target unavailable')
            return original(src, dst, name)

        with mock.patch.object(engine, 'copyFile', side_effect=fail):
            self._run(jobId)
        self.assertEqual(jobMapper.getSourceSnapshot(jobId)['entries'], old)
        self._run(jobId)
        self.assertNotEqual(jobMapper.getSourceSnapshot(jobId)['entries'], old)

    def test_move_resumes_source_deletion_without_recopy(self):
        write(self.src, 'a', b'new')
        jobId = self._job(sourceMode=1, method=2)
        self.interrupt_after_file(jobId, 'a')
        with mock.patch.object(JobTask, 'copyFile', autospec=True) as copy:
            self._run(jobId)
        copy.assert_not_called()
        self.assertFalse((self.base / 'src/a').exists())

    def test_checkpoint_rolls_back_when_job_identity_changes(self):
        write(self.src, 'a', b'new')
        jobId = self._job(sourceMode=1)
        job = jobService.getJobClientById(jobId).job
        identity = jobMapper.sourceSnapshotIdentity(job)
        identity['srcPath'] = '/different/'
        with self.assertRaises(RuntimeError):
            jobMapper.checkpointSourceFile(jobId, {'path': 'a', 'size': 3}, identity)
        self.assertEqual(jobMapper.getSourceSnapshot(jobId)['entries'], [])

    def test_file_replaced_by_directory_survives_abort(self):
        write(self.src, 'parent', b'old')
        jobId = self._job(sourceMode=1)
        self._run(jobId)
        (self.base / 'src/parent').unlink()
        write(self.src, 'parent/a', b'new')
        saved = self.interrupt_after_file(jobId, 'parent/a')
        entries = {e['path']: e for e in saved['entries']}
        self.assertEqual(entries['parent']['isDir'], 1)
        self.assertEqual(saved['meta']['entryCount'], len(entries))
        with mock.patch.object(JobTask, 'copyFile', autospec=True) as copy:
            self._run(jobId)
        copy.assert_not_called()
        self.assertEqual((self.base / 'dst/parent/a').read_bytes(), b'new')

    def test_directory_replaced_by_file_survives_abort(self):
        write(self.src, 'parent/a', b'old')
        jobId = self._job(sourceMode=1)
        self._run(jobId)
        (self.base / 'src/parent/a').unlink()
        (self.base / 'src/parent').rmdir()
        write(self.src, 'parent', b'new')
        saved = self.interrupt_after_file(jobId, 'parent')
        self.assertEqual([e['path'] for e in saved['entries']], ['parent'])
        self.assertEqual(saved['meta']['entryCount'], 1)
        with mock.patch.object(JobTask, 'copyFile', autospec=True) as copy:
            self._run(jobId)
        copy.assert_not_called()
        self.assertEqual((self.base / 'dst/parent').read_bytes(), b'new')

    def test_periodic_full_compare_with_already_current_target(self):
        write(self.src, 'a', b'old')
        second = self._dir('second')
        self._mount('E', second)
        jobId = self._job(sourceMode=1, dst='/D/:/E/')
        self._run(jobId)
        write(self.src, 'a', b'new-size')
        write(second, 'a', b'new-size')
        # Force the source to have no previous fingerprint so E is recognized
        # solely by its matching size, while D needs a copy.
        with closing(sqlite3.connect(config.sysConfig['db']['dbname'])) as conn:
            with conn:
                conn.execute('delete from job_source_snapshot where jobId=?', (jobId,))
                conn.execute('update job_source_snapshot_meta set entryCount=0, fullScanTime=1 where jobId=?', (jobId,))
        saved = self.interrupt_after_file(jobId, 'a')
        self.assertEqual(saved['meta']['fullScanTime'], 1)
        with mock.patch.object(JobTask, 'copyFile', autospec=True) as copy:
            self._run(jobId)
        copy.assert_not_called()

    def test_incremental_move_repairs_lost_target_before_source_deletion(self):
        jobId = self._job(sourceMode=1, method=2)
        self._run(jobId)
        write(self.src, 'a', b'new')
        self.interrupt_after_file(jobId, 'a')
        (self.base / 'dst/a').unlink()
        self._run(jobId)
        self.assertFalse((self.base / 'src/a').exists())
        self.assertEqual((self.base / 'dst/a').read_bytes(), b'new')
