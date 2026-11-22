import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from common.sqlInit import init_sql
from service.syncJob import jobService


class JobLastRunTests(unittest.TestCase):
    def test_latest_run_reports_file_totals_separately_from_operation_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'history.db'
            config = {'db': {'dbname': str(database)}, 'server': {'password': 'test'}}
            with patch('common.sqlBase.getConfig', return_value=config), \
                    patch('common.sqlInit.getConfig', return_value=config):
                init_sql()
                with closing(sqlite3.connect(database)) as conn, conn:
                    conn.executescript('''
                        insert into job (id) values (1), (2), (3);
                        insert into job_task (id, jobId, createTime, taskNum) values
                            (10, 1, 101, null), (11, 1, 101, '{"duration":12,"sumSize":1110}'),
                            (20, 2, 100, null);
                        insert into job_task_item (taskId, status, type, isPath, fileSize) values
                            (10, 2, 0, 0, 10000),
                            (11, 2, 0, 0, 1024), (11, 2, 2, 0, 64), (11, 2, 0, 0, 0),
                            (11, 2, 0, 1, null), (11, 2, 1, 0, 22),
                            (11, 7, 0, 0, 256), (11, 7, 1, 0, 32), (11, 7, 0, 1, null),
                            (11, 4, 0, 0, 2048);
                    ''')
                rows = jobService.getJobList({'pageSize': 10, 'pageNum': 1})['dataList']

        tasks = {row['id']: row['lastTask'] for row in rows}
        latest = tasks[1]
        self.assertEqual((latest['successFileNum'], latest['successFileSize']), (3, 1088))
        self.assertEqual((latest['failNum'], latest['failFileSize']), (3, 288))
        self.assertEqual((latest['successNum'], latest['allNum'], latest['duration']), (5, 9, 12))
        empty = tasks[2]
        self.assertEqual((empty['successFileNum'], empty['successFileSize'],
                          empty['failNum'], empty['failFileSize']), (0, 0, 0, 0))
        self.assertIsNone(tasks[3])
