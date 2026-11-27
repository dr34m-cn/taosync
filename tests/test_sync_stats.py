import json
import threading
import unittest
from unittest.mock import patch

from common import config
from service.syncJob import taskService
from service.system import syncStats


class SyncStatsTest(unittest.TestCase):
    item = dict(isPath=0, type=0, fileSize=20, fileName='private')

    def setUp(self):
        self.settings = {'anonymous_stats': True}
        self.enterContext(patch.object(config, 'sysConfig', {'server': self.settings}))
        self.enterContext(patch.object(syncStats, '_slots', threading.BoundedSemaphore(2)))
        self.http = self.enterContext(patch.object(syncStats, 'HTTPSConnection'))
        self.tls = self.enterContext(patch.object(syncStats.ssl, 'create_default_context'))
        self.errors = self.enterContext(patch.object(threading, 'excepthook'))
        self.workers = []

        def worker(**kwargs):
            thread = threading.Thread(**kwargs)
            self.workers.append(thread)
            return thread

        self.enterContext(patch.object(syncStats, 'Thread', side_effect=worker))
        self.addCleanup(self.join_workers)

    def join_workers(self):
        for worker in self.workers:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        self.errors.assert_not_called()

    def test_sends_only_current_file_totals_to_fixed_https_endpoint(self):
        syncStats.report([self.item, dict(isPath=0, type=2, fileSize=8), dict(isPath=0, type=0, fileSize=0),
                          dict(isPath=1, type=0, fileSize=None), dict(isPath=0, type=1, fileSize=70)])
        self.join_workers()
        self.http.assert_called_once_with('taoapi.dr34m.cn', timeout=5, context=self.tls.return_value)
        conn = self.http.return_value
        conn.request.assert_called_once_with('POST', '/v1/stats', body=json.dumps({'files': 3, 'bytes': 28}),
                                             headers={'Content-Type': 'application/json'})
        conn.getresponse.return_value.close.assert_called_once_with()
        conn.close.assert_called_once_with()

    def test_empty_or_disabled_runs_never_send(self):
        syncStats.report([])
        with patch.object(config, 'sysConfig', None), patch.object(config, 'getConfig') as load:
            syncStats.report([self.item])
            load.assert_not_called()
        self.settings['anonymous_stats'] = False
        syncStats.report([self.item])
        self.assertFalse(self.workers)
        self.settings['anonymous_stats'] = True
        syncStats.report([dict(isPath=1, type=0), dict(isPath=0, type=1)])
        self.join_workers()
        self.http.assert_not_called()

    def test_opt_out_during_aggregation_discards_report(self):
        def rows():
            self.settings['anonymous_stats'] = False
            yield self.item
        syncStats.report(rows())
        self.join_workers()
        self.http.assert_not_called()

    def test_slow_report_does_not_hold_task_completion_or_queue_other_runs(self):
        entered, release = threading.Event(), threading.Event()

        def stall():
            entered.set()
            release.wait(5)
            raise TimeoutError

        self.http.return_value.getresponse.side_effect = stall
        mapper = self.enterContext(patch.object(taskService, 'jobMapper'))
        mapper.getJobByTaskId.return_value = dict(remark='', srcPath='/a', dstPath='/b')
        notifier = self.enterContext(patch.object(taskService, 'notifyService'))
        notifier.getNotifyList.return_value = [{}]
        self.enterContext(patch.object(taskService, 'G', side_effect=lambda key: [''] * 9 if key == 'task_status' else ''))
        with self.assertNoLogs(level='DEBUG'):
            try:
                taskService.updateJobTaskStatus(1, 2, createTime=1, taskList={2: [self.item], 7: [], -1: []})
                self.assertTrue(entered.wait(2))
                self.assertTrue(self.workers[0].is_alive())
                self.assertTrue(self.workers[0].daemon)
                mapper.updateJobTaskStatus.assert_called_once_with(1, 2, None)
                mapper.updateJobTaskNumMany.assert_called_once()
                notifier.sendNotify.assert_called_once()
                syncStats.report([self.item])
                syncStats.report([self.item])
                self.assertEqual(len(self.workers), 2)
            finally:
                release.set()
                self.join_workers()
            self.assertEqual(self.http.return_value.request.call_count, 2)

    def test_start_and_worker_failures_are_silent_and_release_capacity(self):
        with self.assertNoLogs(level='DEBUG'):
            with patch.object(syncStats, 'Thread') as thread:
                thread.return_value.start.side_effect = RuntimeError('cannot start thread')
                for _ in range(3):
                    syncStats.report([self.item])
                self.assertEqual(thread.return_value.start.call_count, 3)
            syncStats.report([{}])
            self.join_workers()
            self.http.assert_not_called()
            conn = self.http.return_value
            for failure in (OSError('unreachable'), RuntimeError('unexpected failure')):
                conn.request.side_effect = failure
                syncStats.report([self.item])
                self.join_workers()
            conn.request.side_effect = None
            conn.getresponse.return_value.status = 503
            syncStats.report([self.item])
            self.join_workers()
            self.assertEqual(conn.request.call_count, 3)
            self.assertEqual(conn.close.call_count, 3)
