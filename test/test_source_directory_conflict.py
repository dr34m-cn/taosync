import tempfile
import unittest
from pathlib import Path
from unittest import mock

from service.storage.drivers.local import LocalDriver
from service.syncJob.jobClient import JobTask


class SourceDirectoryConflictTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.driver = LocalDriver({'root_path': self.temp.name})
        self.task = JobTask.__new__(JobTask)
        self.task.job = {'method': 1, 'srcPath': '/src/', 'scanIntervalT': 0,
                         'minFileSize': None, 'maxFileSize': None}
        self.task.taskId = 1
        self.task.breakFlag = False
        self.task.finish = []
        self.task.sourceSnapshot = {'item': {'path': 'item', 'isDir': 0, 'size': 3}}
        self.task.alistClient = mock.Mock()
        self.task.alistClient.deleteFile.side_effect = self.delete
        self.task.readDirectory = mock.Mock(side_effect=self.read)
        self.task.copyFile = mock.Mock(side_effect=self.copy)
        self.previous = [{'path': 'item', 'isDir': 1, 'size': None},
                         {'path': 'item/nested', 'isDir': 1, 'size': None},
                         {'path': 'item/nested/old', 'isDir': 0, 'size': 3}]
        (self.root / 'item/nested').mkdir(parents=True)
        (self.root / 'item/nested/old').write_bytes(b'old')

    def read(self, path, *args):
        return ({entry['name'] + ('/' if entry['is_dir'] else ''):
                 {} if entry['is_dir'] else entry['size']
                 for entry in self.driver.list(path)}, {})

    def delete(self, parent, names, interval):
        for name in names:
            try:
                self.driver.delete(parent + name)
            except FileNotFoundError:
                pass

    def copy(self, src, dst, name, size, **_kwargs):
        (self.root / name).write_bytes(b'new')

    def run_sync(self):
        self.task.syncFromSourceSnapshot(self.previous, ['/'])

    def test_replaces_nested_directory_and_allows_snapshot_commit(self):
        self.run_sync()
        self.assertEqual((self.root / 'item').read_bytes(), b'new')
        self.assertTrue(all(item['status'] == 2 for item in self.task.finish))
        self.task.sourceScanAttempted = True
        self.task.sourceScanFailed = False
        self.assertTrue(self.task._allOperationsSuccessful())

    def test_untracked_or_excluded_file_blocks_replacement(self):
        (self.root / 'item/keep').write_bytes(b'keep')
        self.run_sync()
        self.assertEqual((self.root / 'item/keep').read_bytes(), b'keep')
        self.task.copyFile.assert_not_called()
        self.assertTrue(any(item['status'] == 7 for item in self.task.finish))
        for call in self.task.readDirectory.call_args_list:
            self.assertEqual(len(call.args), 3)  # No exclusion spec or cache.
            self.assertEqual(call.args[1], 0)

    def test_size_filtered_old_file_is_preserved(self):
        self.task.job['minFileSize'] = 3
        self.previous[-1]['size'] = 2
        (self.root / 'item/nested/old').write_bytes(b'xx')
        self.run_sync()
        self.assertEqual((self.root / 'item/nested/old').read_bytes(), b'xx')
        self.task.copyFile.assert_not_called()

    def test_unknown_empty_directory_is_preserved(self):
        (self.root / 'item/unknown').mkdir()
        self.run_sync()
        self.assertTrue((self.root / 'item/unknown').is_dir())
        self.task.copyFile.assert_not_called()

    def test_scan_failure_blocks_copy(self):
        self.task.readDirectory.side_effect = OSError('offline')
        self.run_sync()
        self.task.copyFile.assert_not_called()
        self.assertTrue(any(item['status'] == 7 for item in self.task.finish))

    def test_directory_delete_failure_blocks_copy(self):
        original = self.delete

        def fail_directory(parent, names, interval):
            if names == ['item']:
                raise PermissionError('cannot remove directory')
            original(parent, names, interval)

        self.task.alistClient.deleteFile.side_effect = fail_directory
        self.run_sync()
        self.task.copyFile.assert_not_called()
        self.assertTrue((self.root / 'item').is_dir())
        self.assertTrue(any(item['status'] == 7 for item in self.task.finish))

    def test_retry_after_directory_was_already_replaced(self):
        self.driver.delete('/item')
        (self.root / 'item').write_bytes(b'new')
        self.previous = self.previous[:1]
        self.run_sync()
        self.assertEqual((self.root / 'item').read_bytes(), b'new')
        self.task.copyFile.assert_called_once()

    def test_filtered_replacement_does_not_remove_directory_shell(self):
        self.task.job['maxFileSize'] = 2
        self.run_sync()
        self.assertTrue((self.root / 'item').is_dir())
        self.task.copyFile.assert_not_called()

    def test_add_only_and_move_do_not_remove_directory_shell(self):
        for method in (0, 2):
            with self.subTest(method=method):
                self.task.job['method'] = method
                self.task.copyFile.side_effect = None
                self.run_sync()
                self.assertTrue((self.root / 'item/nested/old').is_file())
                self.task.alistClient.deleteFile.assert_not_called()

    def test_abort_preserves_directory(self):
        self.task.breakFlag = True
        self.run_sync()
        self.task.copyFile.assert_not_called()
        self.assertTrue((self.root / 'item/nested/old').is_file())


if __name__ == '__main__':
    unittest.main()
