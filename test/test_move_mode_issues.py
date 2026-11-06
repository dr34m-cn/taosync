"""Move-mode and OpenList (external engine) regressions for issues #215, #218, #234 and #240."""
import os
import sqlite3
import time
from pathlib import Path
from unittest import mock

from common import config
from fake_alist import FakeAlist
from service.alist import alistClient
from service.storage.drivers.local import LocalDriver
from test_builtin_engine_sync import EngineTestBase, tree, write

PARSE_TIME_ERROR = 'parsing time'


class MoveAndOpenListIssueTest(EngineTestBase):
    def _openList(self, **storages):
        fake = FakeAlist()
        for mount, (root, driver, delay) in storages.items():
            fake.storage('/' + mount, root, driver=driver, dirSizeDelay=delay)
        url = fake.start()
        conn = sqlite3.connect(config.sysConfig['db']['dbname'])
        engineId = conn.execute("insert into alist_list(remark, url, userName, token) values ('fake', ?, 'admin', 't')",
                                (url,)).lastrowid
        conn.commit()
        conn.close()
        return fake, engineId

    def _failUploads(self, predicate, message='rejected'):
        original = LocalDriver.upload

        def upload(driver, path, *args, **kwargs):
            if predicate(driver, path):
                raise OSError(message)
            return original(driver, path, *args, **kwargs)

        patcher = mock.patch.object(LocalDriver, 'upload', upload)
        patcher.start()
        self.addCleanup(patcher.stop)

    # ------------------------------------------------------------ #215
    def test_move_removes_source_directories_emptied_by_the_run(self):
        write(self.src, 'show/s01/e01.mkv', 'episode-1')
        write(self.src, 'show/s02/e01.mkv', 'episode-2')
        os.makedirs(Path(self.src, 'show', 's02', 'extras'))
        write(self.src, 'keep/tiny.txt', 'x')              # below minFileSize -> directory kept
        write(self.src, 'keep/big.txt', 'big-file')
        write(self.src, 'skip/file.tmp', 'excluded')        # excluded -> directory kept
        write(self.src, 'skip/ok.txt', 'ok-file')
        write(self.src, 'fail/bad.txt', 'bad-file')         # copy fails -> directory kept
        os.makedirs(Path(self.src, 'untouched-empty'))      # never held a moved file -> kept
        self._failUploads(lambda driver, path: path.endswith('bad.txt'))
        status, _, items = self._run(self._job(method=2, exclude='*.tmp', minSize=5))
        self.assertEqual(status, 3)
        self.assertFalse(Path(self.src, 'show').exists())
        for kept in ('keep/tiny.txt', 'skip/file.tmp', 'fail/bad.txt'):
            self.assertTrue(Path(self.src, kept).exists(), kept)
        self.assertTrue(Path(self.src, 'untouched-empty').is_dir())
        self.assertTrue(Path(self.src).is_dir())
        self.assertEqual(tree(self.dst).get('show/s02/e01.mkv'), b'episode-2')
        removedDirs = [item for item in items if item[1] == 2 and item[0] is None and item[2] == 2]
        self.assertEqual(len(removedDirs), 3)  # show/s01, show/s02, show

    def test_move_directory_cleanup_is_skipped_on_abort(self):
        write(self.src, 'd/a.bin', b'a')
        self._slowUploads(1.0)
        job = self._job(method=2)
        from service.syncJob import jobService
        jobService.doJobManual(job)
        time.sleep(0.3)
        jobService.abortJob(job)
        self._wait(jobService.getJobClientById(job))
        self.assertTrue(Path(self.src, 'd').is_dir())

    # ------------------------------------------------------------ #234
    def test_multi_target_move_deletes_each_file_only_after_every_target_succeeds(self):
        second = self._dir('dst2')
        self._mount('D2', second)
        write(self.src, 'a/m.txt', 'move me')
        write(self.src, 'a/n.txt', 'and me')
        self._failUploads(lambda driver, path: driver.root == os.path.realpath(second) and path.endswith('m.txt'))
        job = self._job(method=2, dst='/D/:/D2/')
        status, _, _ = self._run(job)
        self.assertEqual(status, 3)
        self.assertTrue(Path(self.src, 'a', 'm.txt').exists())
        self.assertFalse(Path(self.src, 'a', 'n.txt').exists())
        self.assertEqual(tree(second).get('a/n.txt'), b'and me')
        mock.patch.stopall()
        status, _, _ = self._run(job)
        self.assertEqual(status, 2)
        self.assertFalse(Path(self.src, 'a').exists())
        self.assertEqual(tree(second).get('a/m.txt'), b'move me')

    def test_move_keeps_source_when_target_copy_is_incomplete(self):
        write(self.src, 'video.mkv', b'v' * 4096)
        fake, engineId = self._openList(src=(self.src, 'Local', 0), dst=(self.dst, 'Local', 0))
        fake.copyFaults.append({'dst_prefix': '/dst', 'match': lambda n: True, 'mode': 'truncate'})
        status, _, items = self._run(self._job(method=2, src='/src/', dst='/dst/', engineId=engineId))
        self.assertEqual(status, 3)
        self.assertTrue(Path(self.src, 'video.mkv').exists())
        self.assertIn('4096', items[0][3])

    # ------------------------------------------------------------ #240
    def test_engine_error_after_delivery_is_verified_as_success(self):
        write(self.src, 'a.txt', 'alpha')
        write(self.src, 'sub/b.txt', 'bravo')
        fake, engineId = self._openList(src=(self.src, 'Local', 0), tianyi=(self.dst, '189CloudPC', 0))
        fake.copyFaults.append({'dst_prefix': '/tianyi', 'match': lambda n: True, 'mode': 'write_then_fail'})
        status, _, items = self._run(self._job(method=2, src='/src/', dst='/tianyi/', engineId=engineId))
        self.assertEqual(status, 2)
        self.assertEqual(tree(self.dst).get('sub/b.txt'), b'bravo')
        self.assertFalse(Path(self.src, 'a.txt').exists())
        noted = [item for item in items if item[3] and PARSE_TIME_ERROR in item[3]]
        self.assertEqual({item[2] for item in noted}, {2})

    def test_real_engine_failure_or_stale_same_size_target_stays_failed(self):
        write(self.src, 'a.txt', 'NEWER')
        write(self.dst, 'a.txt', 'older')                    # same size, different content
        write(self.src, 'b.txt', 'bravo')
        fake, engineId = self._openList(src=(self.src, 'Local', 0), tianyi=(self.dst, '189CloudPC', 0))
        fake.copyFaults.append({'dst_prefix': '/tianyi', 'match': lambda n: n == 'a.txt', 'mode': 'write_then_fail'})
        fake.copyFaults.append({'dst_prefix': '/tianyi', 'match': lambda n: n == 'b.txt', 'mode': 'fail'})
        status, _, _ = self._run(self._job(method=2, src='/src/', dst='/tianyi/', engineId=engineId))
        self.assertEqual(status, 3)
        self.assertTrue(Path(self.src, 'a.txt').exists())
        self.assertTrue(Path(self.src, 'b.txt').exists())

    # ------------------------------------------------------------ #218
    def test_openlist_local_storage_is_listed_without_refresh(self):
        for i in range(3):
            write(self.src, f'd{i}/f.txt', 'x')
        fake, engineId = self._openList(local=(self.src, 'Local', 2.0), cloud=(self.dst, 'AliyundriveOpen', 0))
        start = time.time()
        status, _, _ = self._run(self._job(method=0, src='/local/', dst='/cloud/', engineId=engineId))
        self.assertEqual(status, 2)
        self.assertLess(time.time() - start, 6)
        self.assertFalse([call for call in fake.listCalls if call[0].startswith('/local') and call[1]])
        self.assertTrue([call for call in fake.listCalls if call[0].startswith('/cloud') and call[1]])
        from service.engine import engineService
        client = engineService.getClientById(engineId)
        fake.listCalls.clear()
        client.filePathList('/local/')
        self.assertEqual(fake.listCalls, [('/local/', False)])

    def test_refresh_kept_when_storage_list_is_unavailable(self):
        client = alistClient.AlistClient.__new__(alistClient.AlistClient)
        client.storageDrivers = None
        client.storageDriversTime = 0.0
        import threading
        client.storageLock = threading.Lock()
        client.get = mock.Mock(side_effect=Exception('403 permission denied'))
        self.assertTrue(client.shouldRefresh('/local/a'))
        self.assertFalse(client.shouldRefresh('/local/a', useCache=1))
        client.storageDrivers = {'/local': 'local', '/local/nested': 'aliyundriveopen'}
        client.storageDriversTime = time.monotonic()
        self.assertFalse(client.shouldRefresh('/local/a'))
        self.assertTrue(client.shouldRefresh('/local/nested/x'))
        self.assertTrue(client.shouldRefresh('/localx/y'))

    def test_alist_browsing_runs_concurrently(self):
        from controller import jobController
        self.assertGreater(jobController.Alist.executor._max_workers, 1)
