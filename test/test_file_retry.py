"""Single-file retry safety on local mounts and a temporary database."""
import json
import threading
from unittest import mock

from common import LNG
from mapper import jobMapper
from service.alist.alistClient import AlistClient
from service.syncJob import jobService, taskService
from test_builtin_engine_sync import EngineTestBase, tree, write


class FileRetrySafetyTest(EngineTestBase):
    def failed_item(self, job_id, operation, parent='', error='original'):
        task = jobMapper.addJobTask({'jobId': job_id, 'runTime': 1})
        jobMapper.updateJobTaskStatus(task, 3)
        jobMapper.addJobTaskItemMany([dict(taskId=task, srcPath=None if operation == 1 else '/S/' + parent,
                                           dstPath='/D/' + parent, fileName='one', fileSize=1, isPath=0,
                                           type=operation, alistTaskId=None, status=7, errMsg=error)])
        return task, jobMapper.getJobTaskItemList({'taskId': task})[0]['id']

    def retry(self, job, task, item):
        jobService.retryFile(task, item)
        self._wait(jobService.getJobClientById(job))
        row, = jobService.getTaskDetails({'taskId': task})
        self.assertEqual((row['status'], row['errMsg']), (7, 'original'))
        return row['retry']

    def test_stored_reason_uses_viewer_language_on_every_read(self):
        job = self._job()
        task, item = self.failed_item(job, 1)
        write(self.dst, 'one', b'1')
        run = self.retry(job, task, item)['id']
        for stored in (jobMapper.getJobTaskById(run), *jobMapper.getJobTaskItemList({'taskId': run})):
            self.assertEqual(json.loads(stored['retryReason']), ['source_empty_protect', '/S/', '/D/'])
            self.assertIsNone(stored['errMsg'])
        page = dict(pageNum=1, pageSize=10)
        for lang in ('en', 'zh_CN', 'en'):
            LNG.set_context_lang(lang)
            expected = LNG.G('source_empty_protect', lang).format('/S/', '/D/')
            linked, = jobService.getTaskDetails({'taskId': task, **page})['dataList']
            detail, = jobService.getTaskDetails({'taskId': run})
            history = taskService.getTaskList({'id': job, **page})['dataList']
            latest, = jobService.getJobList(page.copy())['dataList']
            for row in (linked['retry'], detail, next(r for r in history if r['id'] == run), latest['lastTask']):
                self.assertEqual(row['errMsg'], expected)
                self.assertNotIn('retryReason', row)
            self.assertEqual(linked['errMsg'], 'original')
        # No task-level reason: the linked result takes its reason from the failed file.
        jobMapper.updateJobTaskStatus(run, 3)
        self.assertEqual(jobService.getTaskDetails({'taskId': task})[0]['retry']['errMsg'], expected)

    def test_old_text_and_external_errors_are_never_translation_keys(self):
        job = self._job()
        previous = '来源路径已存在同名项，已阻止删除'
        task, item = self.failed_item(job, 1, error=previous)
        diagnostic = 'file_retry_source_conflict'
        with mock.patch.object(jobService.FileRetryTask, 'readDirectory', side_effect=OSError(diagnostic)):
            run = jobService.retryFile(task, item)['id']
            self._wait(jobService.getJobClientById(job))
        for lang in ('zh_CN', 'en'):
            LNG.set_context_lang(lang)
            original, = jobService.getTaskDetails({'taskId': task})
            self.assertEqual((original['errMsg'], original['retry']['errMsg']), (previous, diagnostic))
            self.assertEqual(jobService.getTaskDetails({'taskId': run})[0]['errMsg'], diagnostic)

    def test_retry_request_rejections_follow_request_language(self):
        job = self._job()
        task, item = self.failed_item(job, 0)
        write(self.src, 'one', b'1')
        self.assertEqual(self.retry(job, task, item)['status'], 2)
        for lang, ineligible, repeated in (
                ('en', 'Only failed files from finished tasks can be retried',
                 'This file has already been retried. Refresh to see the result.'),
                ('zh_CN', '只可重试已结束任务中的失败文件', '该文件已重试，请刷新查看结果')):
            LNG.set_context_lang(lang)
            for candidate, expected in ((-1, ineligible), (item, repeated)):
                with self.assertRaises(ValueError) as error:
                    jobService.retryFile(task, candidate)
                self.assertEqual(str(error.exception), expected)

    def test_copy_retry_reads_only_named_file(self):
        job = self._job()
        task, item = self.failed_item(job, 0)
        write(self.src, 'one', b'1')
        with mock.patch.object(jobService.FileRetryTask, 'readDirectory', side_effect=AssertionError) as scan:
            self.assertEqual(self.retry(job, task, item)['status'], 2)
            scan.assert_not_called()
        client = object.__new__(AlistClient)
        with mock.patch.object(client, 'post', return_value=dict(name='one', is_dir=False, size=1)) as request:
            self.assertEqual(client.fileDetail('/S/', 'one')['size'], 1)
            request.assert_called_once_with('/api/fs/get', data={'path': '/S/one'})

    def test_append_single_then_bulk_to_same_run_and_keep_individual_results(self):
        job = self._job()
        task, one = self.failed_item(job, 0)
        template, = jobMapper.getJobTaskItemList({'taskId': task})
        jobMapper.addJobTaskItemMany([dict(template, fileName=name) for name in ('two', 'missing')])
        write(self.src, 'one', b'1')
        write(self.src, 'two', b'2')
        two = next(row['id'] for row in jobMapper.getJobTaskItemList({'taskId': task}) if row['fileName'] == 'two')
        entered, resume = threading.Event(), threading.Event()
        original = jobService.FileRetryTask.retryFile

        def hold_first(worker):
            if worker.item['id'] == one:
                entered.set()
                resume.wait(10)
            original(worker)

        with mock.patch.object(jobService.FileRetryTask, 'retryFile', hold_first), \
                mock.patch.object(taskService.notifyService, 'getNotifyList') as notifications, \
                mock.patch.object(taskService.jobLinkMapper, 'finishAndEnqueue') as links:
            run = jobService.retryFile(task, one)['id']
            try:
                self.assertTrue(entered.wait(5))
                self.assertEqual(jobService.retryFile(task, two), {'id': run, 'count': 1})
                self.assertEqual(jobService.retryFiles(task), {'id': run, 'count': 1})
                self.assertEqual(jobService.retryFiles(task)['count'], 0)
                current = jobService.getJobCurrent(job)
                self.assertTrue(current['fileRetry'])
                self.assertEqual(current['num']['wait'], 2)
            finally:
                resume.set()
            self._wait(jobService.getJobClientById(job))
            notifications.assert_not_called()
            links.assert_not_called()
        rows = jobService.getTaskDetails({'taskId': task})
        self.assertEqual({r['fileName']: r['retry']['status'] for r in rows}, {'one': 2, 'two': 2, 'missing': 6})
        self.assertEqual(jobMapper.getJobTaskById(run)['status'], 3)
        write(self.src, 'missing', b'3')
        later = jobService.retryFiles(task)
        self.assertNotEqual(later['id'], run)
        self.assertEqual(later['count'], 1)
        self._wait(jobService.getJobClientById(job))
        self.assertEqual(jobService.retryFiles(task), {'id': None, 'count': 0})

    def test_delete_requires_nonempty_source_after_exclusions(self):
        job = self._job(exclude='*.tmp')
        task, item = self.failed_item(job, 1)
        write(self.src, 'marker.tmp', b'x')
        write(self.dst, 'one', b'1')
        result = self.retry(job, task, item)
        self.assertEqual(tree(self.dst), {'one': b'1'})
        self.assertEqual(result['status'], 6)
        self.assertTrue(result['errMsg'])
        write(self.src, 'visible', b'x')
        self.assertEqual(self.retry(job, task, item)['status'], 2)
        self.assertEqual(tree(self.dst), {})

    def test_move_retries_current_bytes_to_all_targets_and_keeps_parent(self):
        other = self._dir('other')
        self._mount('E', other)
        job = self._job(method=2, dst='/D/:/E/')
        task, item = self.failed_item(job, 2, 'nested/')
        write(self.src, 'nested/one', b'new')
        write(self.src, 'unrelated', b'keep')
        write(other, 'nested/one', b'old')
        self.assertEqual(self.retry(job, task, item)['status'], 2)
        self.assertEqual(tree(self.src), {'nested/': 'DIR', 'unrelated': b'keep'})
        for target in (self.dst, other):
            self.assertEqual(tree(target), {'nested/': 'DIR', 'nested/one': b'new'})
