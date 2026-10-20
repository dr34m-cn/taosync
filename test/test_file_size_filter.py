import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from common import config, sqlBase, sqlInit
from service.syncJob import jobService
from service.syncJob.jobClient import JobTask, isFileSizeAllowed


class FileSizeFilterPredicateTest(unittest.TestCase):
    def test_no_boundaries_allow_every_file_size(self):
        self.assertTrue(isFileSizeAllowed(0))
        self.assertTrue(isFileSizeAllowed(10**12))

    def test_boundaries_are_inclusive(self):
        self.assertFalse(isFileSizeAllowed(99, 100, 200))
        self.assertTrue(isFileSizeAllowed(100, 100, 200))
        self.assertTrue(isFileSizeAllowed(200, 100, 200))
        self.assertFalse(isFileSizeAllowed(201, 100, 200))

    def test_zero_is_a_real_upper_boundary(self):
        self.assertTrue(isFileSizeAllowed(0, maxFileSize=0))
        self.assertFalse(isFileSizeAllowed(1, maxFileSize=0))


class FileSizeFilterInputTest(unittest.TestCase):
    @staticmethod
    def _job(**overrides):
        job = {
            'enable': 1,
            'isCron': 0,
            'exclude': None,
        }
        job.update(overrides)
        return job

    def test_older_clients_default_both_boundaries_to_none(self):
        job = self._job()

        jobService.cleanJobInput(job)

        self.assertIsNone(job['minFileSize'])
        self.assertIsNone(job['maxFileSize'])

    def test_integer_strings_are_normalized_to_bytes(self):
        job = self._job(minFileSize=' 1024 ', maxFileSize='2048')

        jobService.cleanJobInput(job)

        self.assertEqual(job['minFileSize'], 1024)
        self.assertEqual(job['maxFileSize'], 2048)

    def test_negative_fractional_boolean_and_reversed_values_are_rejected(self):
        invalid_values = [
            {'minFileSize': -1},
            {'maxFileSize': 1.5},
            {'minFileSize': True},
            {'maxFileSize': '1.5'},
            {'minFileSize': 2, 'maxFileSize': 1},
        ]

        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(Exception):
                jobService.cleanJobInput(self._job(**values))


class FileSizeFilterSchemaTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / 'taoSync.db')
        self.original_config = config.sysConfig
        config.sysConfig = {
            'db': {'dbname': self.db_path},
            'server': {
                'password': config.DEFAULT_PASSWORD,
                'passwdStr': 'test-secret',
            },
        }
        sqlBase.RUN_FLAG = False

    def tearDown(self):
        config.sysConfig = self.original_config
        sqlBase.RUN_FLAG = False
        self.temp_dir.cleanup()

    def _job_columns(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return {
                row[1]: {'type': row[2], 'default': row[4]}
                for row in conn.execute('pragma table_info(job)').fetchall()
            }
        finally:
            conn.close()

    def test_new_database_contains_nullable_integer_boundaries(self):
        with mock.patch('common.commonUtils.generatePasswd', return_value='generated'):
            sqlInit.init_sql()

        columns = self._job_columns()
        self.assertEqual(columns['minFileSize']['type'].upper(), 'INTEGER')
        self.assertEqual(columns['maxFileSize']['type'].upper(), 'INTEGER')
        self.assertIn(columns['minFileSize']['default'], (None, 'NULL'))
        self.assertIn(columns['maxFileSize']['default'], (None, 'NULL'))

    def test_existing_database_is_migrated_without_changing_old_jobs(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute('create table user_list (sqlVersion integer)')
            conn.execute('insert into user_list (sqlVersion) values (250608)')
            conn.execute('create table job (id integer primary key, remark text)')
            conn.execute("insert into job (id, remark) values (1, 'existing')")
            conn.commit()
        finally:
            conn.close()

        sqlInit.init_sql()

        columns = self._job_columns()
        self.assertIn('minFileSize', columns)
        self.assertIn('maxFileSize', columns)
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                'select minFileSize, maxFileSize from job where id = 1'
            ).fetchone()
            version = conn.execute('select sqlVersion from user_list').fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(row, (None, None))
        self.assertEqual(version, sqlInit.CU_VERSION)


class FileSizeFilterSyncTest(unittest.TestCase):
    @staticmethod
    def _task(method=1, min_size=100, max_size=200):
        task = JobTask.__new__(JobTask)
        task.job = {
            'method': method,
            'minFileSize': min_size,
            'maxFileSize': max_size,
            'scanIntervalT': 0,
        }
        task.breakFlag = False
        task.copy_operations = []
        task.delete_operations = []
        task.copyFile = lambda src, dst, name, size: task.copy_operations.append(
            (src, dst, name, size)
        )
        task.delFile = lambda path, name, size: task.delete_operations.append(
            (path, name, size)
        )
        return task

    def test_existing_target_comparison_skips_filtered_source_files(self):
        task = self._task(method=0)
        source = {
            'below.bin': 99,
            'at-min.bin': 100,
            'inside.bin': 150,
            'at-max.bin': 200,
            'above.bin': 201,
        }
        task.listDir = lambda _path, _first, _spec, _root, isSrc=True: (
            source if isSrc else {}
        )

        task.syncWithHave('/src/', '/dst/', None, '/src/', '/dst/', True)

        self.assertEqual(
            [item[2] for item in task.copy_operations],
            ['at-min.bin', 'inside.bin', 'at-max.bin'],
        )

    def test_full_sync_never_deletes_a_target_for_a_filtered_same_name_source(self):
        task = self._task(method=1)
        source = {'filtered.bin': 99}
        target = {'filtered.bin': 150}
        task.listDir = lambda _path, _first, _spec, _root, isSrc=True: (
            source if isSrc else target
        )

        task.syncWithHave('/src/', '/dst/', None, '/src/', '/dst/', True)

        self.assertEqual(task.copy_operations, [])
        self.assertEqual(task.delete_operations, [])

    def test_full_sync_only_deletes_target_only_files_inside_the_range(self):
        task = self._task(method=1)
        source = {}
        target = {
            'below.bin': 99,
            'at-min.bin': 100,
            'inside.bin': 150,
            'at-max.bin': 200,
            'above.bin': 201,
        }
        task.listDir = lambda _path, _first, _spec, _root, isSrc=True: (
            source if isSrc else target
        )

        task.syncWithHave('/src/', '/dst/', None, '/src/', '/dst/', True)

        self.assertEqual(
            [item[1] for item in task.delete_operations],
            ['at-min.bin', 'inside.bin', 'at-max.bin'],
        )

    def test_target_only_directory_is_scanned_instead_of_deleted_wholesale(self):
        task = self._task(method=1)
        listings = {
            ('/src/', True): {},
            ('/dst/', False): {'extra/': {}},
            ('/dst/extra/', False): {
                'below.bin': 99,
                'inside.bin': 150,
                'nested/': {},
            },
            ('/dst/extra/nested/', False): {
                'at-max.bin': 200,
                'above.bin': 201,
            },
        }
        task.listDir = lambda path, _first, _spec, _root, isSrc=True: listings[
            (path, isSrc)
        ]

        task.syncWithHave('/src/', '/dst/', None, '/src/', '/dst/', True)

        self.assertEqual(
            task.delete_operations,
            [
                ('/dst/extra/', 'inside.bin', 150),
                ('/dst/extra/nested/', 'at-max.bin', 200),
            ],
        )

    def test_missing_target_path_only_queues_allowed_source_files(self):
        task = self._task(method=2)
        task.alistClient = mock.Mock()
        task.copyHook = mock.Mock()
        task.listDir = mock.Mock(return_value={
            'below.bin': 99,
            'inside.bin': 150,
            'above.bin': 201,
        })

        task.syncWithOutHave('/src/new/', '/dst/new/', None, '/src/', '/dst/', True)

        self.assertEqual(
            [item[2] for item in task.copy_operations],
            ['inside.bin'],
        )

    def test_without_a_size_filter_target_only_directories_keep_legacy_deletion(self):
        task = self._task(method=1, min_size=None, max_size=None)
        source = {}
        target = {'extra/': {}}
        task.listDir = lambda _path, _first, _spec, _root, isSrc=True: (
            source if isSrc else target
        )

        task.syncWithHave('/src/', '/dst/', None, '/src/', '/dst/', True)

        self.assertEqual(task.delete_operations, [('/dst/', 'extra/', {})])


if __name__ == '__main__':
    unittest.main()
