import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

import tornado.testing
import tornado.web

from common import LNG, commonUtils, config, locales, sqlBase, sqlInit
from common.intervalGate import IntervalGate
from controller import baseController, systemController
from mapper import userMapper
from service.alist.alistClient import AlistClient
from service.storage import storageService
from service.syncJob import jobClient
from service.syncJob.jobClient import CopyItem, JobClient, JobTask
from service.system import userService


def _key(key, *_args, **_kwargs):
    return key


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class IntervalGateTest(unittest.TestCase):
    def test_sequential_requests_are_spaced_by_the_full_interval(self):
        clock = FakeClock()
        gate = IntervalGate(clock=clock, sleep=clock.sleep)
        fired = []
        for _ in range(4):
            gate.wait('root', 5)
            fired.append(clock.now)
        self.assertEqual(fired, [100.0, 105.0, 110.0, 115.0])

    def test_idle_time_longer_than_interval_does_not_wait(self):
        clock = FakeClock()
        gate = IntervalGate(clock=clock, sleep=clock.sleep)
        gate.wait('root', 5)
        clock.now += 30
        self.assertEqual(gate.wait('root', 5), 0.0)

    def test_zero_interval_and_other_keys_are_independent(self):
        clock = FakeClock()
        gate = IntervalGate(clock=clock, sleep=clock.sleep)
        gate.wait('a', 5)
        self.assertEqual(gate.wait('b', 5), 0.0)
        self.assertEqual(gate.wait('a', 0), 0.0)

    def test_concurrent_threads_get_distinct_slots(self):
        gate = IntervalGate()
        delays = []
        lock = threading.Lock()

        def worker():
            delay = gate.wait('root', 0.05)
            with lock:
                delays.append(delay)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        delays.sort()
        # Each thread reserves its own slot: the n-th waits about n intervals.
        for index, delay in enumerate(delays):
            self.assertGreaterEqual(delay, index * 0.05 - 0.02, delays)

    def test_alist_client_throttles_per_top_level_directory(self):
        clock = FakeClock()
        client = AlistClient.__new__(AlistClient)
        client.waitGate = IntervalGate(clock=clock, sleep=clock.sleep)
        client.checkWait('/mnt/a/', 3)
        client.checkWait('/mnt/b/', 3)
        self.assertEqual(clock.now, 103.0)
        client.checkWait('/other/x/', 3)
        self.assertEqual(clock.now, 103.0)
        client.checkWait('/mnt/c/', 3)
        self.assertEqual(clock.now, 106.0)


class TaskTimeoutConfigTest(unittest.TestCase):
    def setUp(self):
        self.original_cwd = os.getcwd()
        self.original_config = config.sysConfig
        self.temp_dir = tempfile.TemporaryDirectory()
        os.chdir(self.temp_dir.name)
        Path('data').mkdir()
        config.sysConfig = None

    def tearDown(self):
        config.sysConfig = self.original_config
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def _load(self, ini):
        Path('data/config.ini').write_text('[tao]\n' + ini, encoding='utf-8')
        config.sysConfig = None
        with mock.patch.object(config, 'getPasswordStr', return_value='secret'):
            return config.getConfig()['server']['timeout']

    def test_documented_task_timeout_key_is_read(self):
        self.assertEqual(self._load('task_timeout=5\n'), 5)

    def test_legacy_timeout_key_still_works(self):
        self.assertEqual(self._load('timeout=7\n'), 7)

    def test_timeout_hours_convert_to_seconds_and_zero_disables(self):
        with mock.patch.object(jobClient, 'getConfig', return_value={'server': {'timeout': 2}}):
            self.assertEqual(jobClient.taskTimeoutSeconds(), 7200)
        with mock.patch.object(jobClient, 'getConfig', return_value={'server': {'timeout': 0}}):
            self.assertEqual(jobClient.taskTimeoutSeconds(), 0)


def _bare_task(**attrs):
    task = JobTask.__new__(JobTask)
    task.taskId = 1
    task.job = {'method': 0, 'srcPath': '/src/', 'dstPath': '/dst/', 'scanIntervalT': 0,
                'minFileSize': None, 'maxFileSize': None}
    task.finish = []
    task.doing = {}
    task.waiting = deque()
    task.breakFlag = False
    task.finalized = False
    task.timedOut = False
    task.timeoutSeconds = 0
    task.createTime = time.time()
    task.lastWatching = time.time()
    task.scanFinish = True
    task.firstSync = None
    task.queueNum = 0
    task.sourceScanAttempted = False
    task.sourceScanFailed = False
    task.alistClient = mock.Mock()
    for key, value in attrs.items():
        setattr(task, key, value)
    return task


class CopyItemStatusTest(unittest.TestCase):
    def setUp(self):
        patches = [
            mock.patch.object(jobClient, 'G', side_effect=_key),
            mock.patch('service.syncJob.jobClient.time.sleep'),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.task = _bare_task()
        self.item = CopyItem('/src/', '/dst/', 'a.bin', 10, 0, self.task)
        self.item.alistTaskId = 'tid'

    def test_transient_status_errors_are_retried(self):
        self.task.alistClient.taskInfo.side_effect = [
            Exception('read timeout'), Exception('connection reset'),
            {'state': 2, 'progress': 100, 'error': ''},
        ]
        self.item.checkAndGetStatus()
        self.assertEqual(self.item.status, 2)
        self.task.alistClient.copyTaskDelete.assert_called_once_with('tid')

    def test_persistent_status_errors_fail_after_retry_limit(self):
        self.task.alistClient.taskInfo.side_effect = Exception('engine down')
        self.item.checkAndGetStatus()
        self.assertEqual(self.item.status, 7)
        self.assertEqual(self.task.alistClient.taskInfo.call_count, jobClient.MAX_TASK_INFO_FAILURES)

    def test_missing_task_fails_immediately(self):
        self.task.alistClient.taskInfo.side_effect = Exception('404 not found')
        self.item.checkAndGetStatus()
        self.assertEqual(self.item.status, 7)
        self.assertEqual(self.item.errMsg, 'task_may_delete')
        self.assertEqual(self.task.alistClient.taskInfo.call_count, 1)


class JobTaskStateTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(jobClient, 'G', side_effect=_key)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_hooks_use_call_time_instead_of_import_time(self):
        task = _bare_task()
        with mock.patch('service.syncJob.jobClient.time.time', return_value=12345.6):
            task.copyHook('/src/', '/dst/', None, None, isPath=1)
            task.delHook('/dst/', 'x', 1)
        self.assertEqual([item['createTime'] for item in task.finish], [12345, 12345])

    def test_results_after_finalization_are_ignored(self):
        task = _bare_task(finalized=True)
        task.copyHook('/src/', '/dst/', 'late', 1)
        self.assertEqual(task.finish, [])

    def test_unfinished_copies_are_recorded_once_after_abort_drain(self):
        task = _bare_task(breakFlag=True)
        item = CopyItem('/src/', '/dst/', 'stuck.bin', 5, 0, task)
        item.doingKey = 1
        task.doing[1] = item
        with mock.patch.object(jobClient, 'ABORT_DRAIN_SECONDS', 0):
            task._drainAfterBreak()
        self.assertEqual(task.doing, {})
        self.assertEqual([(i['fileName'], i['status'], i['errMsg']) for i in task.finish],
                         [('stuck.bin', 7, 'copy_interrupted')])
        task.completeCopy(item)
        self.assertEqual(len(task.finish), 1)

    def test_completed_copy_moves_from_doing_to_finish(self):
        task = _bare_task()
        item = CopyItem('/src/', '/dst/', 'ok.bin', 5, 0, task)
        item.doingKey = 3
        item.status = 2
        task.doing[3] = item
        task.completeCopy(item)
        self.assertEqual(task.doing, {})
        self.assertEqual(task.finish[0]['status'], 2)

    def test_progress_snapshot_survives_concurrent_queue_changes(self):
        task = _bare_task(scanFinish=False)
        stop = threading.Event()
        errors = []

        def mutate():
            key = 0
            while not stop.is_set():
                key += 1
                item = CopyItem('/src/', '/dst/', f'{key}.bin', 1, 0, task)
                item.doingKey = key
                with task._stateLock():
                    task.doing[key] = item
                    task.waiting.append(item)
                with task._stateLock():
                    task.waiting.popleft()
                task.completeCopy(item)

        workers = [threading.Thread(target=mutate) for _ in range(3)]
        for worker in workers:
            worker.start()
        try:
            for _ in range(300):
                try:
                    task.getCurrent()
                except RuntimeError as exc:
                    errors.append(exc)
                    break
        finally:
            stop.set()
            for worker in workers:
                worker.join()
        self.assertEqual(errors, [])

    def test_timeout_aborts_and_reports_timeout_status(self):
        task = _bare_task(timeoutSeconds=10, createTime=time.time() - 20)
        self.assertTrue(task.checkTimeout())
        self.assertTrue(task.breakFlag)
        with mock.patch.object(jobClient.taskService, 'updateJobTaskStatus') as update:
            task.updateTaskStatus()
        self.assertEqual(update.call_args.args[1], 5)

    def test_abort_persists_unfinished_copy_and_releases_job(self):
        task = _bare_task(breakFlag=True, jobClient=mock.Mock())
        item = CopyItem('/src/', '/dst/', 'stuck.bin', 5, 0, task)
        item.doingKey = 1
        task.doing[1] = item
        with mock.patch.object(jobClient, 'ABORT_DRAIN_SECONDS', 0.1), \
                mock.patch.object(jobClient.jobMapper, 'addJobTaskItemMany') as persist, \
                mock.patch.object(jobClient.taskService, 'updateJobTaskStatus') as update:
            task.taskSubmit()
        self.assertEqual(persist.call_args.args[0][0]['fileName'], 'stuck.bin')
        self.assertEqual(update.call_args.args[1], 7)
        task.jobClient.finishRun.assert_called_once_with(task)
        self.assertTrue(task.finalized)


class SharedSchedulerTest(unittest.TestCase):
    def test_jobs_share_one_scheduler_and_removal_keeps_others(self):
        base = {'isCron': 0, 'interval': 60, 'method': 0}
        enabled = JobClient(dict(base, id=990001, enable=1))
        disabled = JobClient(dict(base, id=990002, enable=0))
        try:
            scheduler = jobClient.getScheduler()
            self.assertIs(enabled.scheduled, scheduler)
            self.assertIs(disabled.scheduled, scheduler)
            self.assertIsNone(disabled.scheduledJob.next_run_time)
            disabledJobId = disabled.scheduledJob.id
            enabled.stopJob(remove=True)
            self.assertIsNone(enabled.scheduledJob)
            self.assertTrue(scheduler.running)
            self.assertIsNotNone(scheduler.get_job(disabledJobId))
        finally:
            enabled.stopJob(remove=True)
            disabled.stopJob(remove=True)


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / 'taoSync.db')
        self.original_config = config.sysConfig
        config.sysConfig = {
            'db': {'dbname': self.db_path},
            'server': {'password': 'admin-pass', 'passwdStr': 'test-secret', 'expires': 2},
        }
        self.original_users = userMapper.users
        userMapper.users = {}
        self.original_errors = userService.ERR_PWD
        userService.ERR_PWD = {}
        patcher = mock.patch.object(userService, 'G', side_effect=_key)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        config.sysConfig = self.original_config
        userMapper.users = self.original_users
        userService.ERR_PWD = self.original_errors
        self.temp_dir.cleanup()


class SqlBaseTest(DatabaseTestCase):
    def test_concurrent_writes_are_serialized(self):
        sqlBase.execute_update("create table t (id integer primary key autoincrement, v integer)")
        errors = []

        def worker(offset):
            try:
                for value in range(40):
                    sqlBase.execute_insert("insert into t (v) values (?)", (offset + value,))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i * 100,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(sqlBase.fetch_first_val("select count(*) from t"), 240)

    def test_original_exception_type_is_preserved(self):
        with self.assertRaises(sqlite3.OperationalError):
            sqlBase.fetchall("select * from missing_table")


class LegacyUpgradeTest(DatabaseTestCase):
    """Schema created by v0.2.0, the oldest supported release."""

    LEGACY_SCHEMA = (
        "create table user_list(id integer primary key autoincrement, userName text, passwd text,"
        "createTime integer DEFAULT (strftime('%s', 'now')))",
        "create table alist_list(id integer primary key autoincrement, remark text, url text,"
        "userName text, token text, createTime integer DEFAULT (strftime('%s', 'now')),"
        " unique (url, userName))",
        "create table job(id integer primary key autoincrement, enable integer DEFAULT 1, srcPath text,"
        "dstPath text, alistId integer, speed integer, method integer, interval integer, cron text,"
        "createTime integer DEFAULT (strftime('%s', 'now')), unique (srcPath, dstPath, alistId))",
        "create table job_task(id integer primary key autoincrement, jobId integer,"
        "status integer DEFAULT 1, runTime integer, createTime integer DEFAULT (strftime('%s', 'now')))",
        "create table job_task_item(id integer primary key autoincrement, taskId integer, srcPath text,"
        "dstPath text, fileName text, fileSize integer, type integer, alistTaskId text,"
        "status integer DEFAULT 0, progress real, errMsg text,"
        "createTime integer DEFAULT (strftime('%s', 'now')))",
    )

    def _create_legacy_database(self):
        conn = sqlite3.connect(self.db_path)
        for statement in self.LEGACY_SCHEMA:
            conn.execute(statement)
        conn.execute("insert into user_list(userName, passwd) values ('admin', ?)",
                     (commonUtils.passwd2md5('legacy-pass'),))
        conn.execute("insert into job(srcPath, dstPath, alistId, speed, method, interval) "
                     "values ('/a/', '/b/', 1, 0, 0, 60)")
        conn.execute("insert into job_task(jobId, runTime) values (1, 1700000000)")
        conn.execute("insert into job_task_item(taskId, fileName, status) values (1, 'old.txt', 2)")
        conn.commit()
        conn.close()

    def test_upgrade_adds_indexes_and_keeps_data(self):
        self._create_legacy_database()
        self.assertIsNone(sqlInit.init_sql())
        self.assertIsNone(sqlInit.init_sql())
        conn = sqlite3.connect(self.db_path)
        try:
            indexes = {row[0] for row in conn.execute("select name from sqlite_master where type='index'")}
            version = conn.execute("select sqlVersion from user_list").fetchone()[0]
            items = conn.execute("select count(*) from job_task_item").fetchone()[0]
        finally:
            conn.close()
        self.assertIn('idx_job_task_item_task', indexes)
        self.assertIn('idx_job_task_job', indexes)
        self.assertEqual(version, sqlInit.CU_VERSION)
        self.assertEqual(items, 1)

    def test_legacy_password_still_logs_in_and_is_upgraded(self):
        self._create_legacy_database()
        sqlInit.init_sql()
        user = userService.checkPwd(None, 'legacy-pass', 'admin', clientKey='ip')
        self.assertTrue(user['passwd'].startswith('pbkdf2_sha256$'))
        conn = sqlite3.connect(self.db_path)
        try:
            stored = conn.execute("select passwd from user_list").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(stored, user['passwd'])
        userMapper.users = {}
        self.assertEqual(userService.checkPwd(None, 'legacy-pass', 'admin', clientKey='ip')['id'], user['id'])

    def test_task_items_persist_their_own_create_time(self):
        self._create_legacy_database()
        sqlInit.init_sql()
        from mapper import jobMapper
        jobMapper.addJobTaskItemMany([{
            'taskId': 1, 'srcPath': '/a/', 'dstPath': '/b/', 'isPath': 0, 'fileName': 'new.txt',
            'fileSize': 1, 'type': 0, 'alistTaskId': None, 'status': 2, 'errMsg': None,
            'createTime': 1700000123,
        }])
        rows = jobMapper.getJobTaskItemList({'taskId': 1, 'status': 2})
        self.assertIn(1700000123, [row['createTime'] for row in rows])
        latest = jobMapper.getLatestJobTaskList([1])
        self.assertEqual(latest[0]['itemAllNum'], 2)


class LoginSecurityTest(DatabaseTestCase):
    def setUp(self):
        super().setUp()
        sqlInit.init_sql()

    def test_new_database_stores_pbkdf2_hash(self):
        user = userService.getUser(None, 'admin')
        self.assertTrue(user['passwd'].startswith('pbkdf2_sha256$'))
        self.assertTrue(commonUtils.verifyPasswd('admin-pass', user['passwd']))
        self.assertFalse(commonUtils.verifyPasswd('wrong', user['passwd']))

    def test_failed_logins_lock_only_the_offending_client(self):
        for _ in range(userService.ERR_PWD_MAX + 1):
            with self.assertRaises(Exception):
                userService.checkPwd(None, 'wrong', 'admin', clientKey='10.0.0.9')
        with self.assertRaises(Exception) as locked:
            userService.checkPwd(None, 'admin-pass', 'admin', clientKey='10.0.0.9')
        self.assertEqual(str(locked.exception), 'passwd_wrong_max_time')
        self.assertEqual(userService.checkPwd(None, 'admin-pass', 'admin', clientKey='10.0.0.1')['userName'],
                         'admin')

    def test_session_cookie_has_no_password_hash_and_expires_on_password_change(self):
        user = userService.checkPwd(None, 'admin-pass', 'admin', clientKey='ip')
        cookie = json.loads(baseController.buildSessionCookie(user))
        self.assertNotIn('passwd', cookie)
        self.assertNotIn(user['passwd'], json.dumps(cookie))
        self.assertEqual(baseController.resolveSessionUser(cookie)['id'], user['id'])
        legacy = {'id': user['id'], 'userName': 'admin', 'passwd': user['passwd']}
        self.assertIsNone(baseController.resolveSessionUser(legacy))
        userService.editPasswd(user['id'], 'new-pass', 'admin-pass')
        self.assertIsNone(baseController.resolveSessionUser(cookie))

    def test_generated_passwords_use_secure_random(self):
        with mock.patch.object(commonUtils.secrets, 'choice', return_value='x') as choice:
            self.assertEqual(commonUtils.generatePasswd(4), 'xxxx')
        self.assertEqual(choice.call_count, 4)


JSON_HEADERS = {'Content-Type': 'application/json'}


class LoginHttpTest(tornado.testing.AsyncHTTPTestCase):
    def setUp(self):
        locales.initLang()
        self.original_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        os.chdir(self.temp_dir.name)
        Path('data').mkdir()
        self.original_config = config.sysConfig
        self.original_language = LNG.sysLanguage
        config.sysConfig = {
            'db': {'dbname': str(Path(self.temp_dir.name) / 'data' / 'taoSync.db')},
            'server': {'password': 'admin-pass', 'passwdStr': 'test-secret', 'expires': 2},
        }
        LNG.sysLanguage = None
        self.original_users = userMapper.users
        userMapper.users = {}
        self.original_errors = userService.ERR_PWD
        userService.ERR_PWD = {}
        sqlInit.init_sql()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        config.sysConfig = self.original_config
        LNG.sysLanguage = self.original_language
        userMapper.users = self.original_users
        userService.ERR_PWD = self.original_errors
        os.chdir(self.original_cwd)
        self.temp_dir.cleanup()

    def get_app(self):
        return tornado.web.Application([
            (r"/svr/noAuth/login", systemController.Login),
            (r"/svr/user", systemController.User),
        ], cookie_secret='test-secret')

    def test_login_sets_httponly_session_cookie_without_password_hash(self):
        response = self.fetch('/svr/noAuth/login', method='POST', headers=JSON_HEADERS,
                              body=json.dumps({'userName': 'admin', 'passwd': 'admin-pass'}))
        body = json.loads(response.body)
        self.assertEqual(body['code'], 200)
        self.assertNotIn('passwd', body['data'])
        setCookie = response.headers['Set-Cookie']
        self.assertIn('HttpOnly', setCookie)
        self.assertIn('SameSite=Lax', setCookie)
        cookie = setCookie.split(';', 1)[0]
        user = json.loads(self.fetch('/svr/user', headers={'Cookie': cookie}).body)
        self.assertEqual(user['code'], 200)
        self.assertEqual(user['data']['userName'], 'admin')
        self.assertNotIn('passwd', user['data'])

    def test_wrong_password_is_rejected(self):
        response = self.fetch('/svr/noAuth/login', method='POST', headers=JSON_HEADERS,
                              body=json.dumps({'userName': 'admin', 'passwd': 'nope'}))
        self.assertEqual(json.loads(response.body)['code'], 500)

    def test_request_without_cookie_is_unauthorized(self):
        self.assertEqual(json.loads(self.fetch('/svr/user').body)['code'], 401)


class MountSecretReuseTest(unittest.TestCase):
    def _aliyun_old(self, **config):
        base = {'auth_mode': 'direct', 'client_id': 'app', 'client_secret': 'secret',
                'refresh_token': 'refresh', 'access_token': 'access'}
        base.update(config)
        return {'config': base}

    def test_aliyun_secrets_are_kept_for_the_same_endpoint(self):
        config = storageService._prepareAliyunConfig(
            {'auth_mode': 'direct', 'client_id': 'app', 'client_secret': '', 'refresh_token': ''},
            old=self._aliyun_old(),
        )
        self.assertEqual(config['client_secret'], 'secret')
        self.assertEqual(config['refresh_token'], 'refresh')

    def test_aliyun_secrets_are_not_sent_to_a_changed_endpoint(self):
        for change in ({'oauth_url': 'https://evil.example/token'},
                       {'api_url': 'https://evil.example'},
                       {'client_id': 'other-app'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                storageService._prepareAliyunConfig(
                    dict({'auth_mode': 'direct', 'client_id': 'app'}, **change),
                    old=self._aliyun_old(),
                )

    def test_aliyun_new_secrets_may_accompany_an_endpoint_change(self):
        config = storageService._prepareAliyunConfig(
            {'auth_mode': 'direct', 'client_id': 'app', 'api_url': 'https://proxy.example',
             'client_secret': 'new-secret', 'refresh_token': 'new-refresh'},
            old=self._aliyun_old(),
        )
        self.assertEqual(config['client_secret'], 'new-secret')
        self.assertNotIn('access_token', config)

    def _update(self, driverType, oldConfig, newConfig):
        old = {'id': 7, 'engineId': 1, 'name': 'nas', 'driverType': driverType,
               'config': oldConfig, 'enabled': 1, 'authVersion': 1}
        with mock.patch.object(storageService.storageMapper, 'getMountById', return_value=old), \
                mock.patch.object(storageService, '_requireTaoSync'), \
                mock.patch.object(storageService, '_normalizeDriverConfig', side_effect=lambda _t, c: c), \
                mock.patch.object(storageService.storageMapper, 'updateMount') as update, \
                mock.patch.object(storageService, '_invalidateEngine'):
            storageService.updateMount({'id': 7, 'name': 'nas', 'driverType': driverType, 'config': newConfig})
        return update.call_args.args[0]['config']

    def test_smb_and_ftp_password_reused_only_for_same_target(self):
        for driverType in ('smb', 'ftp'):
            oldConfig = {'host': 'nas.local', 'port': 445 if driverType == 'smb' else 21,
                         'username': 'u', 'password': 'pw', 'share': 's', 'root_path': '/a'}
            with self.subTest(driverType=driverType):
                saved = self._update(driverType, oldConfig,
                                     dict(oldConfig, password='', root_path='/b', host='NAS.local'))
                self.assertEqual(saved['password'], 'pw')
                with self.assertRaises(ValueError):
                    self._update(driverType, oldConfig, dict(oldConfig, password='', host='evil.example'))
                with self.assertRaises(ValueError):
                    self._update(driverType, oldConfig, dict(oldConfig, password='', username='other'))
                saved = self._update(driverType, oldConfig,
                                     dict(oldConfig, password='new', host='other.local'))
                self.assertEqual(saved['password'], 'new')

    def test_smb_share_discovery_does_not_reuse_password_for_other_host(self):
        old = {'engineId': 1, 'driverType': 'smb',
               'config': {'host': 'nas.local', 'username': 'u', 'password': 'pw'}}
        with mock.patch.object(storageService.storageMapper, 'getMountById', return_value=old), \
                mock.patch.object(storageService, '_requireTaoSync'):
            same = storageService._smbRequestConfig(
                {'engineId': 1, 'mountId': 3, 'config': {'host': 'nas.local', 'username': 'u'}})
            other = storageService._smbRequestConfig(
                {'engineId': 1, 'mountId': 3, 'config': {'host': 'evil.example', 'username': 'u'}})
        self.assertEqual(same['password'], 'pw')
        self.assertEqual(other['password'], '')


if __name__ == '__main__':
    unittest.main()
