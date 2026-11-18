import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from common.sqlInit import init_sql
from service.syncJob import taskService


class TaskHistoryStatsTests(unittest.TestCase):
    def test_completed_runs_have_separate_file_stats_and_only_known_times(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory, 'history.db')
            config = {'db': {'dbname': str(database)}, 'server': {'password': 'test'}}
            with patch('common.sqlBase.getConfig', return_value=config), \
                    patch('common.sqlInit.getConfig', return_value=config):
                init_sql()
                with closing(sqlite3.connect(database)) as conn, conn:
                    conn.executescript('''
                        insert into job_task (id,jobId,status,runTime,createTime,taskNum) values
                            (10,1,3,100,100,'{"duration":5}'), (11,1,4,200,200,'{}'),
                            (12,1,1,300,300,'{}'), (13,2,2,400,400,'{}');
                        insert into job_task_item (taskId,status,type,isPath,fileSize) values
                            (10,2,0,0,128), (10,2,0,0,0), (10,2,1,0,256), (10,2,2,0,4),
                            (10,7,0,0,16), (10,2,0,1,null), (10,7,0,1,null), (10,4,0,0,512),
                            (13,2,0,0,1024);
                    ''')
                history = taskService.getTaskList({'id': 1, 'pageNum': 1, 'pageSize': 10})
        tasks = {row['id']: row for row in history['dataList']}
        self.assertEqual(set(tasks), {10, 11, 12})
        self.assertEqual(tasks[10]['endTime'], 105)
        self.assertEqual(tasks[10]['fileStats'], {
            'copy': {'count': 2, 'size': 128}, 'delete': {'count': 1, 'size': 256},
            'move': {'count': 1, 'size': 4}, 'failed': {'count': 1, 'size': 16},
        })
        self.assertIsNone(tasks[11].get('endTime'))
        self.assertEqual(tasks[11]['fileStats'], {})
        self.assertNotIn('fileStats', tasks[12])
