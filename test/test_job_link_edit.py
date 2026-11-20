"""Integration coverage for job links and edits against an isolated SQLite database."""
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest import mock

from apscheduler.schedulers.background import BackgroundScheduler

from common import sqlBase
from mapper import jobLinkMapper, jobMapper
from service.syncJob import jobClient, jobLinks, jobService
from test_builtin_engine_sync import EngineTestBase


class JobLinkEditTest(EngineTestBase):
    def setUp(self):
        super().setUp()
        scheduler = BackgroundScheduler()
        scheduler.start(paused=True)
        self.addCleanup(scheduler.shutdown)
        self.enterContext(mock.patch.object(jobClient, 'getScheduler', return_value=scheduler))

    def _scheduled(self):
        job = self._job()
        jobService.editJobClient(dict(jobMapper.getJobById(job), isCron=0, interval=180))
        return jobService.getJobClientById(job)

    def _check_failed_edit(self, old, edit, error):
        # A three-hour interval is already two minutes from its next delivery.
        due = datetime.now(timezone.utc) + timedelta(minutes=2)
        old.scheduledJob.modify(next_run_time=due)
        saved = jobMapper.getJobById(old.jobId)
        with self.assertRaises(error):
            jobService.editJobClient(dict(saved, **edit))
        current = jobService.getJobClientById(old.jobId)
        self.assertEqual(jobMapper.getJobById(old.jobId), saved)
        self.assertEqual(current.scheduledJob.next_run_time, due)
        self.assertEqual(current.scheduled.get_jobs(), [current.scheduledJob])
        self.assertFalse(current.runLock.locked())

    def test_invalid_cron_preserves_next_run(self):
        self._check_failed_edit(self._scheduled(), {'isCron': 1, 'minute': 'invalid'}, ValueError)

    def test_failed_database_edit_preserves_next_run(self):
        old = self._scheduled()
        sqlBase.execute_update("create trigger reject_edit before update on job begin "
                               "select raise(abort, 'edit rejected'); end")
        self._check_failed_edit(old, {'interval': 90}, sqlite3.IntegrityError)

    def test_log_pages_and_clear_preserve_other_rules_and_pending_deliveries(self):
        source, target, other = [self._job(dst=f'/D/{n}/') for n in range(3)]

        def link(dest):
            return jobLinks.create(dict(source=source, targets=[dest, dest], condition='success', minutes=5))

        first, second = link(target), link(other)
        for n in range(22):
            task = jobMapper.addJobTask(dict(jobId=source, runTime=n))
            self.assertTrue(jobLinkMapper.finishAndEnqueue(task, 2, None, n))
        # Leave the last pair pending; tied timestamps exercise the ID tie-breaker.
        rows = jobLinkMapper.due(320)
        self.assertEqual(len(rows), 42)
        for row in rows:
            self.assertTrue(jobLinkMapper.claim(row['id'], 320))
            jobLinkMapper.setResult(row['id'], 'executed')
        expected = [row['id'] for row in reversed(rows) if row['target'] == target]
        for page, ids in ((1, expected[:20]), (2, expected[20:]), (3, [])):
            history = jobLinks.history(first, page)
            self.assertEqual(history['count'], 21)
            self.assertEqual([row['id'] for row in history['rows']], ids)
        jobLinkMapper.clear(first)
        self.assertEqual(jobLinks.history(first, 1)['count'], 0)
        self.assertEqual(jobLinks.history(second, 1)['count'], 21)
        jobLinkMapper.clear()
        self.assertEqual(jobLinks.history(second, 1)['count'], 0)
        self.assertEqual(sorted(row['target'] for row in jobLinkMapper.due(321)), sorted([target, other]))
