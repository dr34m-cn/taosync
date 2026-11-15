import configparser
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, unquote

from common import config
from service.notify import custom, notifyService, push
from service.syncJob import jobClient


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.temp = tempfile.TemporaryDirectory()
        os.chdir(self.temp.name)
        Path('data').mkdir()
        self.previous = config.sysConfig
        config.sysConfig = None
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.secret = mock.patch.object(config, 'getPasswordStr', return_value='test-secret')
        self.secret.start()

    def tearDown(self):
        config.sysConfig = self.previous
        self.secret.stop()
        self.env.stop()
        os.chdir(self.cwd)
        self.temp.cleanup()

    def test_default_is_15_days_and_old_hours_are_converted(self):
        self.assertEqual(config.getSettings()['source_full_scan_days'], 15)
        for hours, days in ((24, 1), (1, 1 / 24), (0, 0)):
            Path('data/config.ini').write_text(f'[tao]\nsource_full_scan_hours={hours}\n', encoding='utf-8')
            config.sysConfig = None
            self.assertEqual(config.getSettings()['source_full_scan_days'], days)
        config.updateSettings({'timeout': 10})
        self.assertNotIn('source_full_scan_hours', Path('data/config.ini').read_text())

    def test_new_environment_days_win_over_legacy_hours(self):
        with mock.patch.dict(os.environ, {'TAO_SOURCE_FULL_SCAN_DAYS': '15', 'TAO_SOURCE_FULL_SCAN_HOURS': '24'}):
            self.assertEqual(config.getSettings()['source_full_scan_days'], 15)
        config.sysConfig = None
        with mock.patch.dict(os.environ, {'TAO_SOURCE_FULL_SCAN_HOURS': '48'}):
            self.assertEqual(config.getSettings()['source_full_scan_days'], 2)

    def test_partial_ini_uses_environment_for_missing_keys_and_default_last(self):
        Path('data/config.ini').write_text('[tao]\ntask_save=0\n', encoding='utf-8')
        with mock.patch.dict(os.environ, {'TAO_TASK_SAVE': '9', 'TAO_TASK_TIMEOUT': '8',
                                         'TAO_ALIYUN_AUTH_SERVER': 'https://env.example'}):
            self.assertEqual(config.getSettings(), {'task_save': 0, 'timeout': 8,
                             'aliyun_auth_server': 'https://env.example', 'source_full_scan_days': 15})

    def test_file_values_override_environment_after_save_and_restart(self):
        Path('data/config.ini').write_text('[tao]\nport=9000\n', encoding='utf-8')
        env = {'TAO_TASK_SAVE': '9', 'TAO_TASK_TIMEOUT': '8', 'TAO_SOURCE_FULL_SCAN_DAYS': '2',
               'TAO_ALIYUN_AUTH_SERVER': 'https://env.example'}
        expected = {'task_save': 3, 'timeout': 4, 'source_full_scan_days': 15,
                    'aliyun_auth_server': 'https://file.example'}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(config.updateSettings(expected), expected)
            config.sysConfig = None
            self.assertEqual(config.getSettings(), expected)
            self.assertEqual(config.getConfig()['server']['port'], 9000)

    def test_legacy_file_values_override_new_environment_names(self):
        Path('data/config.ini').write_text('[tao]\ntask_timeout=5\nsource_full_scan_hours=48\n', encoding='utf-8')
        with mock.patch.dict(os.environ, {'TAO_TASK_TIMEOUT': '8', 'TAO_SOURCE_FULL_SCAN_DAYS': '15'}):
            self.assertEqual(config.getSettings()['timeout'], 5)
            self.assertEqual(config.getSettings()['source_full_scan_days'], 2)

    def test_invalid_value_does_not_skip_other_higher_priority_settings(self):
        Path('data/config.ini').write_text('[tao]\nport=invalid\ntask_save=3\ntimeout=4\n', encoding='utf-8')
        with mock.patch.dict(os.environ, {'TAO_PORT': '9001', 'TAO_TASK_SAVE': 'invalid', 'TAO_TASK_TIMEOUT': '8'}), \
                self.assertLogs(level='ERROR'):
            self.assertEqual(config.getSettings()['task_save'], 3)
            self.assertEqual(config.getSettings()['timeout'], 4)
            self.assertEqual(config.getConfig()['server']['port'], 9001)

    def test_save_preserves_other_sections_percent_values_and_timeout_alias(self):
        Path('data/config.ini').write_text('[tao]\nport=9001\npassword=a%password\ntask_timeout=72\n'
                                          'custom=keep\n[other]\nvalue=original\n', encoding='utf-8')
        config.updateSettings({'timeout': 12, 'task_save': 7, 'source_full_scan_days': 15,
                               'aliyun_auth_server': 'https://auth.example/path%20name/'})
        self.assertEqual(config.getSettings()['timeout'], 12)
        config.sysConfig = None
        self.assertEqual(config.getSettings()['timeout'], 12)
        server = config.getConfig()['server']
        self.assertEqual(server['port'], 9001)
        self.assertEqual(server['password'], 'a%password')
        parser = configparser.ConfigParser(interpolation=None)
        parser.read('data/config.ini', encoding='utf-8')
        self.assertEqual(parser['tao']['custom'], 'keep')
        self.assertEqual(parser['other']['value'], 'original')
        self.assertNotIn('passwdStr', parser['tao'])

    def test_first_save_only_persists_editable_settings_and_keeps_environment_fallback(self):
        with mock.patch.dict(os.environ, {'TAO_PORT': '9002', 'TAO_PASSWORD': 'a%secret', 'TAO_EXPIRES': '7'}):
            config.updateSettings({'task_save': 3})
            config.sysConfig = None
            server = config.getConfig()['server']
            self.assertEqual((server['port'], server['password'], server['expires']), (9002, 'a%secret', 7))
            parser = configparser.ConfigParser(interpolation=None)
            parser.read('data/config.ini', encoding='utf-8')
            self.assertEqual(set(parser['tao']), set(config.EDITABLE_SETTINGS))
            os.environ['TAO_PORT'] = '9003'
            config.sysConfig = None
            self.assertEqual(config.getConfig()['server']['port'], 9003)

    def test_failed_disk_write_does_not_change_runtime_or_original_file(self):
        Path('data/config.ini').write_text('[tao]\ntimeout=72\n', encoding='utf-8')
        original = Path('data/config.ini').read_bytes()
        with mock.patch.object(config.os, 'replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                config.updateSettings({'timeout': 1})
        self.assertEqual(config.getSettings()['timeout'], 72)
        self.assertEqual(Path('data/config.ini').read_bytes(), original)
        self.assertEqual(list(Path('data').glob('config-*.ini')), [])

    def test_invalid_values_leave_config_untouched(self):
        for values in ({'timeout': -1}, {'timeout': 1.5}, {'task_save': True}, {'source_full_scan_days': float('nan')},
                       {'port': 5}, {'aliyun_auth_server': 'file:///tmp'}, {'aliyun_auth_server': ''}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                config.updateSettings(values)
        self.assertFalse(Path('data/config.ini').exists())

    def test_scan_interval_and_running_timeout_use_updated_settings(self):
        meta = {'fullScanTime': time.time() - 2 * 86400}
        self.assertFalse(jobClient.JobTask.fullScanDue(meta))
        config.updateSettings({'source_full_scan_days': 1})
        self.assertTrue(jobClient.JobTask.fullScanDue(meta))
        config.updateSettings({'source_full_scan_days': 0})
        self.assertFalse(jobClient.JobTask.fullScanDue(meta))
        task = SimpleNamespace(timeoutSeconds=72 * 3600, timedOut=False, breakFlag=False,
                               createTime=time.time() - 2 * 3600, taskId=1)
        self.assertFalse(jobClient.JobTask.checkTimeout(task))
        config.updateSettings({'timeout': 1})
        self.assertTrue(jobClient.JobTask.checkTimeout(task))


class NotificationTest(unittest.TestCase):
    def setUp(self):
        self.params = {'url': 'https://notify.example/$title?content=$content', 'method': 'POST',
                       'contentType': 'application/json', 'headers': 'Authorization: Bearer abc\nX-Version: 1',
                       'body': '{"title":"$title","nested":{"text":"$content"},"enabled":true}'}
        self.response = mock.Mock(status_code=200)
        self.title = 'Title / & 中文'
        self.content = 'quotes " backslash \\ newline\n $title $content'

    def test_nested_json_and_url_are_encoded_without_recursive_substitution(self):
        with mock.patch.object(custom.requests, 'request', return_value=self.response) as request:
            custom.send(self.params, self.title, self.content, (10, 30))
        args, kwargs = request.call_args
        self.assertEqual(args[0], 'POST')
        self.assertIn(self.title, unquote(args[1]))
        self.assertNotIn(' ', args[1])
        body = json.loads(kwargs['data'])
        self.assertEqual(body['nested']['text'], self.content)
        self.assertTrue(body['enabled'])
        self.assertEqual(kwargs['headers']['authorization'], 'Bearer abc')
        self.assertEqual(kwargs['headers']['x-version'], '1')
        self.assertEqual(kwargs['timeout'], (10, 30))

    def test_qinglong_lines_form_and_raw_text(self):
        for kind in ('application/json', 'application/x-www-form-urlencoded', 'text/plain'):
            params = dict(self.params, contentType=kind, body='title: $title\ncontent: $content')
            with self.subTest(kind=kind), mock.patch.object(custom.requests, 'request', return_value=self.response) as request:
                custom.send(params, self.title, self.content, (10, 30))
                body = request.call_args.kwargs['data'].decode('utf-8')
                if kind == 'application/json':
                    self.assertEqual(json.loads(body)['content'], self.content)
                elif kind == 'text/plain':
                    self.assertIn(self.content, body)
                else:
                    self.assertEqual(parse_qs(body)['content'], [self.content])

    def test_invalid_templates_fail_before_save_or_network(self):
        for change in ({'url': 'file:///tmp'}, {'method': 'INVALID'}, {'body': '{bad json'},
                       {'headers': 'invalid header'}, {'headers': '{"test": "a\\nb"}'}):
            notify = {'method': 5, 'params': json.dumps(dict(self.params, **change))}
            with self.subTest(change=change), mock.patch.object(notifyService.notifyMapper, 'addNotify') as save:
                with self.assertRaises(ValueError):
                    notifyService.addNewNotify(notify)
                save.assert_not_called()

    def test_bark_device_key_custom_server_options_and_response_failure(self):
        for push, url in (('key123', 'https://api.day.app/key123'), ('https://bark.example/key', 'https://bark.example/key')):
            params = {'push': push, 'isArchive': 0, 'group': 'TaoSync', 'sound': 'bell',
                      'level': 'timeSensitive', 'icon': 'https://example/icon.png', 'url': 'https://example/'}
            self.response.json.return_value = {'code': 200}
            with mock.patch.object(custom.requests, 'post', return_value=self.response) as post:
                custom.sendBark(params, self.title, self.content, (10, 30))
                self.assertEqual(post.call_args.args, (url,))
                self.assertEqual(post.call_args.kwargs['json']['isArchive'], 0)
                self.assertEqual(post.call_args.kwargs['json']['body'], self.content)
                self.response.json.return_value = {'code': 400, 'message': 'invalid key'}
                with self.assertRaisesRegex(ValueError, 'invalid key'):
                    custom.sendBark(params, self.title, self.content, (10, 30))

    def test_non_success_http_and_empty_sync_handling(self):
        self.response.status_code = 503
        with mock.patch.object(custom.requests, 'request', return_value=self.response):
            with self.assertRaisesRegex(ValueError, '503'):
                custom.send(self.params, 'title', 'content', (10, 30))
        for method in (5, 6, 7, 8):
            notify = {'method': method, 'params': json.dumps({'notSendNull': True})}
            with mock.patch.object(custom.requests, 'request') as request, mock.patch.object(custom.requests, 'post') as post:
                notifyService.sendNotify(notify, 'title', 'content', needNotSync=True)
                request.assert_not_called()
                post.assert_not_called()


class PushNotificationTest(unittest.TestCase):
    def setUp(self):
        self.title = 'Title / & 中文'
        self.content = 'quotes " backslash \\ newline\n $title $content'
        self.response = mock.Mock(status_code=200)

    def send(self, method, params):
        notifyService.sendNotify({'method': method, 'params': json.dumps(params)}, self.title, self.content)

    def test_pushplus_default_and_optional_parameters(self):
        for extra in ({}, {'topic': 'group123', 'template': 'markdown', 'channel': 'webhook',
                           'webhook': 'hook-code', 'callbackUrl': 'https://callback.example', 'to': 'recipient'}):
            with self.subTest(extra=extra), mock.patch.object(push.requests, 'post', return_value=self.response) as post:
                self.response.json.return_value = {'code': 200, 'data': 'message-id'}
                self.send(7, dict(token=' test-token ', **extra))
                post.assert_called_once_with(push.PUSHPLUS_URL, json={
                    'token': 'test-token', 'title': self.title, 'content': self.content,
                    'template': 'html', 'channel': 'wechat', **extra,
                }, timeout=(10, 30))

    def test_pushdeer_default_and_custom_api_use_markdown_form_data(self):
        for url, endpoint in ((None, push.PUSHDEER_URL), ('', push.PUSHDEER_URL),
                              (' https://deer.example/message/push ', 'https://deer.example/message/push')):
            with self.subTest(url=url), mock.patch.object(push.requests, 'post', return_value=self.response) as post:
                self.response.json.return_value = {'code': 0, 'content': {'result': ['accepted']}}
                self.send(8, {'pushkey': ' test-key ', 'url': url})
                post.assert_called_once_with(endpoint, data={
                    'pushkey': 'test-key', 'text': self.title, 'desp': self.content, 'type': 'markdown',
                }, timeout=(10, 30))

    def test_invalid_settings_are_rejected_before_save_edit_or_send(self):
        cases = [(7, params) for params in ({}, {'token': ' '}, {'token': 123},
                 {'token': 'test', 'template': 'invalid'}, {'token': 'test', 'channel': 'invalid'},
                 {'token': 'test', 'callbackUrl': 'file:///tmp'}, {'token': 'test', 'topic': []})]
        cases += [(8, params) for params in ({}, {'pushkey': ' '}, {'pushkey': 123},
                  {'pushkey': 'test', 'url': 'file:///tmp'}, {'pushkey': 'test', 'url': 123})]
        for method, params in cases:
            with self.subTest(method=method, params=params), \
                    mock.patch.object(notifyService.notifyMapper, 'addNotify') as add, \
                    mock.patch.object(notifyService.notifyMapper, 'editNotify') as edit, \
                    mock.patch.object(push.requests, 'post') as post:
                notify = {'method': method, 'params': json.dumps(params)}
                for action in (notifyService.addNewNotify, notifyService.editNotify):
                    with self.assertRaises(ValueError):
                        action(notify)
                with self.assertRaises(ValueError):
                    self.send(method, params)
                add.assert_not_called()
                edit.assert_not_called()
                post.assert_not_called()

    def test_service_errors_and_empty_pushdeer_targets_are_failures(self):
        cases = [(7, {'token': 'test'}, {'code': 400, 'msg': 'invalid token'}, 'invalid token'),
                 (8, {'pushkey': 'test'}, {'code': 1, 'error': 'invalid pushkey'}, 'invalid pushkey'),
                 (8, {'pushkey': 'test'}, {'code': 0, 'content': {'result': []}}, 'PushDeer delivery failed'),
                 (8, {'pushkey': 'test'}, {'code': 0}, 'PushDeer delivery failed'),
                 (8, {'pushkey': 'test'}, {'code': 0, 'content': {'result': 'invalid'}}, 'PushDeer delivery failed')]
        for method, params, response, message in cases:
            with self.subTest(response=response), mock.patch.object(push.requests, 'post', return_value=self.response):
                self.response.json.return_value = response
                with self.assertRaisesRegex(ValueError, message):
                    self.send(method, params)

    def test_http_malformed_response_and_timeout_failures(self):
        for method, params in ((7, {'token': 'test'}), (8, {'pushkey': 'test'})):
            with self.subTest(method=method), mock.patch.object(push.requests, 'post', return_value=self.response) as post:
                self.response.status_code = 503
                with self.assertRaisesRegex(ValueError, 'HTTP 503'):
                    self.send(method, params)
                self.response.status_code = 200
                self.response.json.return_value = []
                with self.assertRaisesRegex(ValueError, 'Invalid push service response'):
                    self.send(method, params)
                post.side_effect = push.requests.Timeout('request timed out')
                with self.assertRaises(push.requests.Timeout):
                    self.send(method, params)


if __name__ == '__main__':
    unittest.main()
