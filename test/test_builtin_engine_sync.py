"""End-to-end sync scenarios on the built-in TaoSync engine with local mounts."""
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from common import LNG, config, locales, sqlInit
from mapper import jobMapper, userMapper
from service.engine import engineService
from service.storage import storageService
from service.storage.drivers.local import LocalDriver
from service.syncJob import jobService


def write(root, rel, content):
    path = Path(root, *rel.split('/'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))


def tree(root):
    result = {}
    for current, dirs, files in os.walk(root):
        rel = os.path.relpath(current, root).replace('\\', '/')
        prefix = '' if rel == '.' else rel + '/'
        for name in dirs:
            result[prefix + name + '/'] = 'DIR'
        for name in files:
            result[prefix + name] = Path(current, name).read_bytes()
    return result


class EngineTestBase(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.multiple(locales, allLang={}, sysLang=None))
        self.enterContext(mock.patch.object(LNG, '_local', threading.local()))
        self.enterContext(mock.patch.multiple(engineService, clientList={}, copyLimiters={}, engineLocks={}))
        self.enterContext(mock.patch.object(jobService, 'jobClientList', {}))
        locales.initLang()
        self.originalCwd = os.getcwd()
        self.originalConfig = config.sysConfig
        self.originalLanguage = LNG.sysLanguage
        self.originalUsers = userMapper.users
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        (self.base / 'data').mkdir()
        os.chdir(self.base)
        config.sysConfig = {
            'db': {'dbname': str(self.base / 'data' / 'taoSync.db')},
            'server': {'password': 'pw', 'passwdStr': 'secret', 'expires': 2, 'timeout': 72,
                       'source_full_scan_hours': 24},
        }
        LNG.sysLanguage = None
        userMapper.users = {}
        sqlInit.init_sql()
        engineService.clientList.clear()
        engineService.copyLimiters.clear()
        jobService.jobClientList.clear()
        conn = sqlite3.connect(config.sysConfig['db']['dbname'])
        self.engineId = conn.execute("select id from alist_list where systemKey='taosync'").fetchone()[0]
        conn.close()
        self.src = self._dir('src')
        self.dst = self._dir('dst')
        self._mount('S', self.src)
        self._mount('D', self.dst)

    def tearDown(self):
        for client in list(jobService.jobClientList.values()):
            client.stopJob(remove=True)
            deadline = time.time() + 30
            while client.runLock.locked() and time.time() < deadline:
                time.sleep(0.05)
        jobService.jobClientList.clear()
        engineService.clientList.clear()
        engineService.copyLimiters.clear()
        config.sysConfig = self.originalConfig
        LNG.sysLanguage = self.originalLanguage
        userMapper.users = self.originalUsers
        os.chdir(self.originalCwd)
        self.temp.cleanup()

    # ------------------------------------------------------------ helpers
    def _dir(self, name):
        path = self.base / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _mount(self, name, root):
        storageService.addMount({'engineId': self.engineId, 'name': name, 'driverType': 'local',
                                 'config': {'root_path': root}})

    def _job(self, method=1, sourceMode=0, dst='/D/', scanT=0, src='/S/', engineId=None, exclude=None,
             minSize=None):
        job = {'enable': 1, 'remark': None, 'srcPath': src, 'dstPath': dst,
               'alistId': self.engineId if engineId is None else engineId,
               'useCacheT': 0, 'scanIntervalT': scanT, 'useCacheS': 0, 'scanIntervalS': 0,
               'method': method, 'sourceMode': sourceMode, 'interval': None, 'isCron': 2, 'exclude': exclude,
               'minFileSize': minSize, 'maxFileSize': None}
        for key in ('year', 'month', 'day', 'week', 'day_of_week', 'hour', 'minute', 'second',
                    'start_date', 'end_date'):
            job[key] = None
        before = set(jobService.jobClientList)
        jobService.addJobClient(job)
        return (set(jobService.jobClientList) - before).pop()

    def _wait(self, client, timeout=60):
        deadline = time.time() + timeout
        while client.runLock.locked() and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(client.runLock.locked(), 'job did not finish')

    def _run(self, jobId):
        jobService.doJobManual(jobId)
        self._wait(jobService.getJobClientById(jobId))
        conn = sqlite3.connect(config.sysConfig['db']['dbname'])
        try:
            taskId, status, errMsg = conn.execute(
                "select id, status, errMsg from job_task where jobId=? order by id desc limit 1",
                (jobId,)).fetchone()
            items = conn.execute("select fileName, type, status, errMsg from job_task_item where taskId=?",
                                 (taskId,)).fetchall()
        finally:
            conn.close()
        return status, errMsg, items

    def _slowUploads(self, seconds):
        original = LocalDriver.upload

        def upload(driver, *args, **kwargs):
            time.sleep(seconds)
            return original(driver, *args, **kwargs)

        patcher = mock.patch.object(LocalDriver, 'upload', upload)
        patcher.start()
        self.addCleanup(patcher.stop)



class BuiltinEngineSyncTest(EngineTestBase):
    def test_encrypted_folder_backup_and_restore_through_sync_jobs(self):
        backing = self.base / 'dst' / 'vaults'
        source = Path(self.src)
        payload = os.urandom(3 * 1024 * 1024 + 117)
        write(self.src, '资料/跨块.bin', payload)
        write(self.src, '资料/空文件', b'')
        (source / '空目录').mkdir()
        physical_mount = next(row for row in storageService.getMountList(self.engineId) if row['name'] == 'D')
        for hide_dirs in (False, True):
            with self.subTest(encrypt_dir_names=hide_dirs):
                suffix = str(int(hide_dirs))
                mount_name = 'Crypt' + suffix
                root = backing / suffix
                root.mkdir(parents=True)
                restore_name = 'Restored' + suffix
                restored = self._dir(restore_name)
                self._mount(restore_name, restored)
                storageService.addMount({
                    'engineId': self.engineId, 'name': mount_name, 'driverType': 'crypt',
                    'config': {'target_mount_id': physical_mount['id'], 'target_path': '/vaults/' + suffix,
                               'encryption_key': 'integration-secret', 'encrypt_dir_names': hide_dirs},
                })

                status, error, items = self._run(self._job(dst='/' + mount_name + '/'))
                self.assertEqual(status, 2, (error, items))
                self.assertEqual((root / '资料').is_dir(), not hide_dirs)
                files = [p for p in root.rglob('*') if p.is_file()]
                self.assertEqual(len(files), 2)
                for file in files:
                    self.assertNotIn(file.name, ('跨块.bin', '空文件'))
                    self.assertGreater(file.stat().st_size, 0)
                cipher_file = max(files, key=lambda p: p.stat().st_size)
                wire = cipher_file.read_bytes()
                self.assertNotIn(payload[:256], wire)
                self.assertGreater(len(wire), len(payload))

                # Re-open solely from persisted mount data. Check the logical
                # directory API and then restore via the real scheduler/engine.
                engineService.invalidateClient(self.engineId)
                client = engineService.getClientById(self.engineId)
                self.assertEqual(client.allFileList('/' + mount_name),
                                 {'空目录/': {}, '资料/': {'空文件': 0, '跨块.bin': len(payload)}})
                status, error, items = self._run(self._job(src='/' + mount_name + '/', dst='/' + restore_name + '/'))
                self.assertEqual(status, 2, (error, items))
                restored_file = Path(restored, '资料', '跨块.bin')
                self.assertEqual(hashlib.sha256(restored_file.read_bytes()).digest(), hashlib.sha256(payload).digest())
                self.assertEqual(tree(restored), tree(self.src))

                # Tamper with the last tag after earlier records have streamed.
                # The failed copy must not replace a prior valid destination.
                cipher_file.write_bytes(wire[:-1] + bytes([wire[-1] ^ 1]))
                task = client.copyFile('/' + mount_name + '/资料', '/' + restore_name + '/资料', '跨块.bin')
                client.waitTask(task, 10)
                self.assertEqual(client.taskInfo(task)['state'], 7, client.taskInfo(task))
                self.assertEqual(restored_file.read_bytes(), payload)
                self.assertEqual(list(Path(restored).rglob('*.part')), [])

    def test_sync_to_source_named_child_preserves_siblings_and_reports_this_run(self):
        from service.syncJob import taskService

        write(self.src, 'Photos/first.jpg', b'img')
        write(self.dst, 'unrelated.txt', b'keep')
        job = self._job(src='/S/Photos/', dst='/D/Photos/')
        self.assertEqual(self._run(job)[0], 2)
        self.assertEqual(tree(self.dst), {'Photos/': 'DIR', 'Photos/first.jpg': b'img', 'unrelated.txt': b'keep'})
        task = taskService.getTaskList({'id': job, 'pageNum': 1, 'pageSize': 5})['dataList'][0]
        self.assertEqual(task['fileStats'], {'copy': {'count': 1, 'size': 3}})
        self.assertGreaterEqual(task['endTime'], task['runTime'])
        self.assertEqual(json.loads(task['taskNum'])['endTime'], task['endTime'])

    def test_directory_concurrency_persists_and_updates_only_its_live_limiter(self):
        mounts = {row['name']: row for row in storageService.getMountList(self.engineId)}
        source = engineService.getMountCopyLimiter(mounts['S']['id'])
        destination = engineService.getMountCopyLimiter(mounts['D']['id'])
        self.assertEqual((source.limit, destination.limit), (5, 5))
        destination.tryAcquire()
        with mock.patch.object(storageService, '_invalidateEngine') as invalidate:
            storageService.updateMount({'id': mounts['D']['id'], 'copyConcurrency': 2})
        invalidate.assert_not_called()
        self.assertIs(engineService.getMountCopyLimiter(mounts['D']['id']), destination)
        self.assertEqual((source.limit, destination.limit, destination.active), (5, 2, 1))
        destination.release()
        sqlInit.init_sql()
        rows = {row['name']: row for row in storageService.getMountList(self.engineId)}
        self.assertEqual((rows['S']['copyConcurrency'], rows['D']['copyConcurrency']), (5, 2))
        self.assertEqual(rows['D']['configVersion'], mounts['D']['configVersion'])
        self.assertEqual(rows['D']['authVersion'], mounts['D']['authVersion'])
        self.assertEqual(rows['D']['config'], mounts['D']['config'])

    def test_abort_records_waiting_files_and_never_counts_them_as_delivered(self):
        for index in range(40):
            write(self.src, f'cancel-{index}.bin', b'x')
        original_upload = LocalDriver.upload
        uploads_started = threading.Event()
        uploads_lock = threading.Lock()
        active_uploads = []
        cleanup_started = threading.Event()
        allow_cleanup = threading.Event()

        def blocked_upload(driver, *args, **kwargs):
            cancel = kwargs.get('cancel') or args[4]
            with uploads_lock:
                active_uploads.append(1)
                if len(active_uploads) == 5:
                    uploads_started.set()
            cancel.external.wait(10)
            cleanup_started.set()
            allow_cleanup.wait(10)
            return original_upload(driver, *args, **kwargs)

        with mock.patch.object(LocalDriver, 'upload', blocked_upload):
            job = self._job(method=0)
            jobService.doJobManual(job)
            client = jobService.getJobClientById(job)
            destination = next(row for row in storageService.getMountList(self.engineId) if row['name'] == 'D')
            limiter = engineService.getMountCopyLimiter(destination['id'])
            deadline = time.time() + 5
            while time.time() < deadline:
                task = client.currentJobTask
                if task and task.scanFinish and len(task.waiting) == 35:
                    break
                time.sleep(0.01)
            self.assertTrue(task.scanFinish)
            self.assertEqual(len(task.waiting), 35)
            self.assertEqual(len(task.doing), 5)
            self.assertTrue(uploads_started.wait(5))
            client.abortJob()
            try:
                self.assertTrue(cleanup_started.wait(5))
                self.assertEqual(limiter.active, 5)
            finally:
                allow_cleanup.set()
            self._wait(client)
            self.assertEqual(limiter.active, 0)
        conn = sqlite3.connect(config.sysConfig['db']['dbname'])
        try:
            rows = conn.execute('select fileName, status from job_task_item where fileName is not null').fetchall()
            task_num = json.loads(conn.execute('select taskNum from job_task').fetchone()[0])
        finally:
            conn.close()
        self.assertEqual(len(rows), 40)
        self.assertTrue(all(status == 4 for _, status in rows), rows)
        self.assertEqual(task_num['otherNum'], 40)
        self.assertEqual(tree(self.dst), {})

    # ------------------------------------------------------------ 1
    def test_case_only_rename_keeps_target_files_with_throttled_deletes(self):
        for i in range(4):
            write(self.src, f'Photo{i}.JPG', f'image-{i}')
        job = self._job(method=1, scanT=1)
        self._run(job)
        for i in range(4):
            os.rename(Path(self.src, f'Photo{i}.JPG'), Path(self.src, f'photo{i}.jpg'))
        status, _, _ = self._run(job)
        self.assertEqual(status, 2)
        self.assertEqual(sorted(name.casefold() for name in os.listdir(self.dst)),
                         [f'photo{i}.jpg' for i in range(4)])
        self.assertEqual(tree(self.dst), tree(self.src))

    # ------------------------------------------------------------ 2
    def test_empty_source_root_does_not_wipe_target(self):
        for sourceMode in (0, 1):
            with self.subTest(sourceMode=sourceMode):
                for name in os.listdir(self.src):
                    shutil.rmtree(Path(self.src, name))
                write(self.src, 'sub/a.txt', 'a')
                write(self.src, 'b.txt', 'b')
                job = self._job(method=1, sourceMode=sourceMode)
                self._run(job)
                before = tree(self.dst)
                shutil.rmtree(Path(self.src, 'sub'))
                os.remove(Path(self.src, 'b.txt'))
                status, errMsg, _ = self._run(job)
                self.assertEqual(status, 6)
                self.assertIsNotNone(errMsg)
                self.assertEqual(tree(self.dst), before)
                jobService.removeJobClient(job)

    def test_add_only_still_runs_with_an_empty_source(self):
        write(self.dst, 'keep.txt', 'k')
        status, _, _ = self._run(self._job(method=0))
        self.assertEqual(status, 2)

    # ------------------------------------------------------------ 3
    def test_deleting_a_running_job_leaves_no_rows_or_thread_errors(self):
        for i in range(6):
            write(self.src, f'f{i}.bin', b'x')
        self._slowUploads(0.5)
        job = self._job(method=0)
        errors = []
        original = threading.excepthook
        threading.excepthook = lambda args: errors.append(args.exc_value)
        try:
            jobService.doJobManual(job)
            time.sleep(0.6)
            client = jobService.getJobClientById(job)
            jobService.removeJobClient(job)
            self._wait(client)
            time.sleep(0.2)
        finally:
            threading.excepthook = original
        conn = sqlite3.connect(config.sysConfig['db']['dbname'])
        try:
            counts = [conn.execute(f"select count(*) from {table}").fetchone()[0]
                      for table in ('job_task', 'job_task_item')]
        finally:
            conn.close()
        self.assertEqual(counts, [0, 0])
        self.assertEqual(errors, [])

    def test_startup_removes_orphan_rows_left_by_older_versions(self):
        conn = sqlite3.connect(config.sysConfig['db']['dbname'])
        conn.execute("insert into job_task(id, jobId, runTime) values (900, 12345, 1)")
        conn.execute("insert into job_task_item(taskId, fileName) values (900, 'a')")
        conn.execute("insert into job_task_item(taskId, fileName) values (901, 'b')")
        conn.commit()
        conn.close()
        self.assertEqual(jobMapper.deleteOrphanRows(), 3)
        self.assertEqual(jobMapper.deleteOrphanRows(), 0)

    # ------------------------------------------------------------ 4
    def test_builtin_engine_copies_complete_without_poll_delay(self):
        for i in range(120):
            write(self.src, f'f{i}.txt', 'x')
        job = self._job(method=0)
        start = time.time()
        status, _, _ = self._run(job)
        elapsed = time.time() - start
        self.assertEqual(status, 2)
        self.assertEqual(len(os.listdir(self.dst)), 120)
        # Previously ~6.5 files/s unattended (each copy waited a 2.93 s poll).
        self.assertLess(elapsed, 8, f'{elapsed:.1f}s')

    # ------------------------------------------------------------ 5
    def test_unavailable_source_root_reports_failure(self):
        write(self.src, 'a.txt', 'a')
        job = self._job(method=1)
        self._run(job)
        shutil.rmtree(self.src)
        engineService.clientList.clear()
        status, errMsg, _ = self._run(job)
        self.assertEqual(status, 6)
        self.assertIn('S', errMsg)
        self.assertIn('a.txt', tree(self.dst))

    def test_subdirectory_failure_is_still_partial(self):
        write(self.src, 'ok.txt', 'ok')
        write(self.src, 'sub/x.txt', 'x')
        job = self._job(method=0)
        original = LocalDriver.list

        def failing(driver, path, details=False):
            if driver.root == os.path.realpath(self.src) and path.rstrip('/') == '/sub':
                raise OSError('denied')
            return original(driver, path, details)

        with mock.patch.object(LocalDriver, 'list', failing):
            status, _, _ = self._run(job)
        self.assertEqual(status, 3)

    # ------------------------------------------------------------ 6
    def test_missing_target_root_is_created(self):
        write(self.src, 'a.txt', 'a')
        write(self.src, 'sub/b.txt', 'b')
        status, _, _ = self._run(self._job(method=0, dst='/D/new/backup/'))
        self.assertEqual(status, 2)
        self.assertEqual(tree(Path(self.dst, 'new', 'backup')), tree(self.src))

    def test_missing_directory_error_names_the_directory(self):
        client = engineService.getClientById(self.engineId)
        with self.assertRaises(FileNotFoundError) as caught:
            client.fileListApi('/D/absent/')
        self.assertIn('directory not found: /D/absent', str(caught.exception))

    # ------------------------------------------------------------ 7
    def test_running_manual_job_cannot_be_edited(self):
        write(self.src, 'a.bin', b'a')
        self._slowUploads(1.0)
        job = self._job(method=0)
        jobService.doJobManual(job)
        time.sleep(0.3)
        client = jobService.getJobClientById(job)
        edit = dict(client.job)
        edit['remark'] = 'edited'
        with self.assertRaises(Exception):
            jobService.editJobClient(edit)
        self.assertIs(jobService.getJobClientById(job), client)
        self.assertFalse(client.currentJobTask.breakFlag)
        self._wait(client)
        jobService.editJobClient(edit)
        self.assertEqual(jobService.getJobClientById(job).job['remark'], 'edited')

    # ------------------------------------------------------------ 8
    def test_file_directory_conflicts_converge_in_one_run(self):
        write(self.src, 'x', 'file')
        write(self.dst, 'x/inner.txt', 'old dir')
        write(self.src, 'y/inside.txt', 'dir')
        write(self.dst, 'y', 'old file')
        status, _, _ = self._run(self._job(method=1))
        self.assertEqual(status, 2)
        self.assertEqual(tree(self.dst), tree(self.src))

    # ------------------------------------------------------------ 9
    def test_source_mode_removes_empty_directory_shells_only(self):
        write(self.src, 'keep.txt', 'k')
        write(self.src, 'gone/deep/f.txt', 'f')
        write(self.src, 'protected/p.txt', 'p')
        job = self._job(method=1, sourceMode=1)
        self._run(job)
        write(self.dst, 'protected/user-added.txt', 'mine')
        shutil.rmtree(Path(self.src, 'gone'))
        shutil.rmtree(Path(self.src, 'protected'))
        status, _, _ = self._run(job)
        self.assertEqual(status, 2)
        result = tree(self.dst)
        self.assertNotIn('gone/', result)
        self.assertNotIn('protected/p.txt', result)
        self.assertEqual(result.get('protected/user-added.txt'), b'mine')

    # ------------------------------------------------------------ 10
    def _fullScanTime(self, jobId):
        return jobMapper.getSourceSnapshot(jobId)['meta']['fullScanTime']

    def test_source_mode_periodic_full_scan_repairs_target(self):
        write(self.src, 'keep.txt', 'k')
        job = self._job(method=0, sourceMode=1)
        self._run(job)
        firstFull = self._fullScanTime(job)
        self.assertIsNotNone(firstFull)
        os.remove(Path(self.dst, 'keep.txt'))
        self._run(job)
        self.assertFalse(Path(self.dst, 'keep.txt').exists(), 'incremental run must not scan target')
        self.assertEqual(self._fullScanTime(job), firstFull)
        conn = sqlite3.connect(config.sysConfig['db']['dbname'])
        conn.execute("update job_source_snapshot_meta set fullScanTime=? where jobId=?",
                     (int(time.time()) - 25 * 3600, job))
        conn.commit()
        conn.close()
        self._run(job)
        self.assertTrue(Path(self.dst, 'keep.txt').exists())
        self.assertGreater(self._fullScanTime(job), firstFull - 25 * 3600)

    def test_full_scan_period_zero_disables_periodic_scans(self):
        config.sysConfig['server']['source_full_scan_hours'] = 0
        write(self.src, 'keep.txt', 'k')
        job = self._job(method=0, sourceMode=1)
        self._run(job)
        conn = sqlite3.connect(config.sysConfig['db']['dbname'])
        conn.execute("update job_source_snapshot_meta set fullScanTime=NULL where jobId=?", (job,))
        conn.commit()
        conn.close()
        os.remove(Path(self.dst, 'keep.txt'))
        self._run(job)
        self.assertFalse(Path(self.dst, 'keep.txt').exists())

    def test_old_snapshot_meta_table_gains_full_scan_column(self):
        conn = sqlite3.connect(config.sysConfig['db']['dbname'])
        conn.execute("drop table job_source_snapshot_meta")
        conn.execute("create table job_source_snapshot_meta(jobId integer primary key, initialized integer "
                     "DEFAULT 0, scanTime integer DEFAULT NULL, entryCount integer DEFAULT 0)")
        conn.execute("insert into job_source_snapshot_meta values (7, 1, 100, 3)")
        conn.commit()
        conn.close()
        sqlInit.init_sql()
        meta = jobMapper.getSourceSnapshot(7)['meta']
        self.assertEqual((meta['initialized'], meta['entryCount'], meta['fullScanTime']), (1, 3, None))


if __name__ == '__main__':
    unittest.main()
