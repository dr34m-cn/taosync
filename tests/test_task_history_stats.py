import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from common.sqlInit import init_sql
from mapper import jobMapper
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
                common = dict(taskId=10, srcPath='/s', dstPath='/d', isPath=0, status=2,
                              alistTaskId=None, errMsg=None, createTime=100)
                jobMapper.addJobTaskItemMany([
                    dict(common, fileName='rapid-copy', type=0, fileSize=1024, rapidUpload=True),
                    dict(common, fileName='rapid-move', type=2, fileSize=2048, rapidUpload=True),
                    dict(common, fileName='normal', type=0, fileSize=512),
                ])
                filters = dict(taskId=10, rapidUpload='1', pageSize=1, pageNum=1)
                first = taskService.getTaskItemList(filters.copy())
                second = taskService.getTaskItemList(dict(filters, pageNum=2))
                self.assertEqual(first['count'], 2)
                self.assertEqual([page['dataList'][0]['fileName'] for page in (first, second)],
                                 ['rapid-move', 'rapid-copy'])
                self.assertEqual(taskService.getTaskItemList(dict(filters, status='2', type='2'))['count'], 1)
                self.assertEqual(taskService.getTaskItemList(dict(filters, status='7'))['count'], 0)
                history = taskService.getTaskList({'id': 1, 'pageNum': 1, 'pageSize': 10})
        tasks = {row['id']: row for row in history['dataList']}
        self.assertEqual(set(tasks), {10, 11, 12})
        self.assertEqual(tasks[10]['endTime'], 105)
        self.assertEqual(tasks[10]['fileStats'], {
            'copy': {'count': 4, 'size': 1664}, 'delete': {'count': 1, 'size': 256},
            'move': {'count': 2, 'size': 2052}, 'failed': {'count': 1, 'size': 16},
            'rapidUpload': {'count': 2, 'size': 3072},
        })
        self.assertIsNone(tasks[11].get('endTime'))
        self.assertEqual(tasks[11]['fileStats'], {})
        self.assertNotIn('fileStats', tasks[12])
