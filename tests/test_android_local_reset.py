from http.cookies import SimpleCookie
import json
import os
import re
import sqlite3
import stat
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application, RequestHandler

from common import LNG, commonUtils, config, locales, sqlBase
from controller import baseController
from mapper import userMapper
from service.system import androidShell, userService


ROOT = Path(__file__).resolve().parents[1]


def _create_user_db(db_path, user_name='admin', raw_password='old-password'):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "create table user_list("
            "id integer primary key autoincrement,"
            "userName text,"
            "passwd text,"
            "sqlVersion integer DEFAULT 260718,"
            "createTime integer DEFAULT (strftime('%s', 'now'))"
            ")"
        )
        if user_name is not None:
            conn.execute(
                "insert into user_list(userName, passwd) values (?, ?)",
                (user_name, commonUtils.hashPasswd(raw_password)),
            )
        conn.commit()
    finally:
        conn.close()


class _ShellIndexHandler(RequestHandler):
    def set_default_headers(self):
        androidShell.apply_shell_security_headers(self)

    def get(self):
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        shell_auth = self.settings.get('shell_auth')
        csrf_token = (
            shell_auth.get_csrf_token(self.get_cookie(androidShell.SHELL_COOKIE_NAME))
            if shell_auth is not None
            else None
        )
        if not csrf_token:
            self.write(androidShell.UNAUTH_PLACEHOLDER_HTML)
            return
        self.write(
            androidShell.render_log_page_html(
                '<html lang="zh"><script>var I=/*__SHELL_I18N__*/null;var T=/*__SHELL_TOKEN__*/"";</script></html>',
                self.request.headers.get('Accept-Language'),
                csrf_token=csrf_token,
            )
        )


class _IsolatedDbMixin:
    def _setup_isolated_db(self, user_name='admin', raw_password='old-password'):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self._db_path = os.path.join(self._tmpdir.name, 'taoSync.db')
        _create_user_db(self._db_path, user_name=user_name, raw_password=raw_password)

        orig_config = config.sysConfig
        orig_users = userMapper.users
        orig_errors = userService.ERR_PWD
        orig_sys_lang = LNG.sysLanguage

        config.sysConfig = {
            'db': {'dbname': self._db_path},
            'server': {
                'passwdStr': 'test-secret-key-for-android-shell',
                'password': 'RANDOM',
                'expires': 2,
            },
        }
        userMapper.users = {}
        userService.ERR_PWD = {}
        LNG.sysLanguage = None

        def _restore():
            config.sysConfig = orig_config
            userMapper.users = orig_users
            userService.ERR_PWD = orig_errors
            LNG.sysLanguage = orig_sys_lang

        self.addCleanup(_restore)


class AndroidLocalResetUnitTest(_IsolatedDbMixin, unittest.TestCase):
    def test_reset_primary_password_updates_db_invalidates_session_and_clears_lockout(self):
        self._setup_isolated_db(user_name='admin', raw_password='initial-pass')

        old_user = userService.checkPwd(None, 'initial-pass', 'admin', clientKey='127.0.0.1')
        old_cookie = json.loads(baseController.buildSessionCookie(old_user))
        self.assertIsNotNone(baseController.resolveSessionUser(old_cookie))

        for _ in range(userService.ERR_PWD_MAX + 1):
            with self.assertRaises(Exception):
                userService.checkPwd(None, 'wrong', 'admin', clientKey='127.0.0.1')
        with self.assertRaises(Exception):
            userService.checkPwd(None, 'initial-pass', 'admin', clientKey='127.0.0.1')

        result = userService.resetPrimaryPasswd()
        self.assertEqual(result['userName'], 'admin')
        self.assertEqual(len(result['passwd']), 8)
        self.assertNotEqual(result['passwd'], 'initial-pass')

        self.assertIsNone(baseController.resolveSessionUser(old_cookie))
        with self.assertRaises(Exception):
            userService.checkPwd(None, 'initial-pass', 'admin', clientKey='127.0.0.1')

        userService.clearPwdErrors()
        logged_in = userService.checkPwd(None, result['passwd'], 'admin', clientKey='127.0.0.1')
        self.assertEqual(logged_in['userName'], 'admin')
        self.assertTrue(logged_in['passwd'].startswith('pbkdf2_sha256$'))

    def test_reset_primary_password_supports_renamed_admin_user(self):
        self._setup_isolated_db(user_name='custom-admin', raw_password='old-pass')

        result = userService.resetPrimaryPasswd()
        self.assertEqual(result['userName'], 'custom-admin')
        logged_in = userService.checkPwd(None, result['passwd'], 'custom-admin', clientKey='127.0.0.1')
        self.assertEqual(logged_in['userName'], 'custom-admin')

    def test_reset_primary_password_raises_when_no_user_exists(self):
        self._setup_isolated_db(user_name=None)
        LNG.set_context_lang('en')
        with self.assertRaises(Exception) as ctx:
            userService.resetPrimaryPasswd()
        self.assertIn('User does not exist', str(ctx.exception))

    def test_user_mapper_does_not_update_cache_when_db_update_fails(self):
        self._setup_isolated_db(user_name='admin', raw_password='old-pass')
        user = userMapper.getPrimaryUser()
        original_hash = user['passwd']
        with mock.patch.object(sqlBase, 'execute_update', side_effect=RuntimeError('disk full')):
            with self.assertRaises(RuntimeError):
                userMapper.resetPasswd(user['id'], 'new-hash')
        self.assertEqual(userMapper.users[f"uId-{user['id']}"]['passwd'], original_hash)

    def test_shell_auth_manager_token_file_and_session_bounds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            token_path = os.path.join(tmpdir, 'data', '.shell_token')
            auth = androidShell.ShellAuthManager.create_with_token_file(token_path)
            self.assertEqual(Path(token_path).read_text(encoding='utf-8'), auth.boot_token)
            if os.name != 'nt':
                self.assertEqual(stat.S_IMODE(os.stat(token_path).st_mode), 0o600)

        bounded = androidShell.ShellAuthManager(boot_token='boot-secret', max_sessions=2)
        self.assertIsNone(bounded.authenticate_boot_token('wrong-secret'))
        sid1, csrf1 = bounded.authenticate_boot_token('boot-secret')
        sid2, csrf2 = bounded.authenticate_boot_token('boot-secret')
        sid3, csrf3 = bounded.authenticate_boot_token('boot-secret')
        self.assertFalse(bounded.has_valid_session(sid1))
        self.assertTrue(bounded.verify_session_csrf(sid2, csrf2))
        self.assertTrue(bounded.verify_session_csrf(sid3, csrf3))
        self.assertFalse(bounded.verify_session_csrf(sid2, csrf3))

    def test_local_request_guard_enforces_loopback_origin_headers_and_session_csrf(self):
        auth = androidShell.ShellAuthManager(boot_token='boot-secret')
        sid, csrf = auth.authenticate_boot_token('boot-secret')

        def make_req(remote_ip='127.0.0.1', host='127.0.0.1:8024', protocol='http', headers=None):
            default_headers = {
                'X-TaoSync-Local': '1',
                'X-TaoSync-Shell-Token': csrf,
            }
            return types.SimpleNamespace(
                remote_ip=remote_ip,
                host=host,
                protocol=protocol,
                headers=headers if headers is not None else default_headers,
            )

        self.assertTrue(androidShell.is_allowed_local_reset_request(make_req(), shell_auth=auth, session_id=sid))
        self.assertTrue(androidShell.is_allowed_local_reset_request(
            make_req(remote_ip='::1', host='[::1]:8024'), shell_auth=auth, session_id=sid
        ))
        self.assertTrue(androidShell.is_allowed_local_reset_request(
            make_req(remote_ip='::ffff:127.0.0.1'), shell_auth=auth, session_id=sid
        ))
        self.assertTrue(androidShell.is_allowed_local_reset_request(
            make_req(headers={
                'X-TaoSync-Local': '1',
                'X-TaoSync-Shell-Token': csrf,
                'Origin': 'http://127.0.0.1:8024',
                'Sec-Fetch-Site': 'same-origin',
            }),
            shell_auth=auth,
            session_id=sid,
        ))

        # Fails closed without shell_auth, session_id, or matching CSRF token
        self.assertFalse(androidShell.is_allowed_local_reset_request(make_req(), shell_auth=None, session_id=sid))
        self.assertFalse(androidShell.is_allowed_local_reset_request(make_req(), shell_auth=auth, session_id=None))
        self.assertFalse(androidShell.is_allowed_local_reset_request(make_req(), shell_auth=auth, session_id='forged'))
        self.assertFalse(androidShell.is_allowed_local_reset_request(
            make_req(headers={'X-TaoSync-Local': '1', 'X-TaoSync-Shell-Token': 'wrong-csrf'}),
            shell_auth=auth,
            session_id=sid,
        ))
        self.assertFalse(androidShell.is_allowed_local_reset_request(
            make_req(headers={'X-TaoSync-Local': '1'}),
            shell_auth=auth,
            session_id=sid,
        ))

        # Rejects non-loopback IP, host spoofing, business-port origin, cross-origin, and cross-site
        self.assertFalse(androidShell.is_allowed_local_reset_request(
            make_req(remote_ip='192.168.1.5'), shell_auth=auth, session_id=sid
        ))
        self.assertFalse(androidShell.is_allowed_local_reset_request(
            make_req(host='192.168.1.5:8024'), shell_auth=auth, session_id=sid
        ))
        self.assertFalse(androidShell.is_allowed_local_reset_request(
            make_req(host='evil@127.0.0.1:8024'), shell_auth=auth, session_id=sid
        ))
        self.assertFalse(androidShell.is_allowed_local_reset_request(
            make_req(headers={
                'X-TaoSync-Local': '1',
                'X-TaoSync-Shell-Token': csrf,
                'Origin': 'http://127.0.0.1:8023',
            }),
            shell_auth=auth,
            session_id=sid,
        ))
        self.assertFalse(androidShell.is_allowed_local_reset_request(
            make_req(headers={
                'X-TaoSync-Local': '1',
                'X-TaoSync-Shell-Token': csrf,
                'Origin': 'https://evil.example',
            }),
            shell_auth=auth,
            session_id=sid,
        ))
        self.assertFalse(androidShell.is_allowed_local_reset_request(
            make_req(headers={
                'X-TaoSync-Local': '1',
                'X-TaoSync-Shell-Token': csrf,
                'Origin': 'null',
            }),
            shell_auth=auth,
            session_id=sid,
        ))
        self.assertFalse(androidShell.is_allowed_local_reset_request(
            make_req(headers={
                'X-TaoSync-Local': '1',
                'X-TaoSync-Shell-Token': csrf,
                'Sec-Fetch-Site': 'cross-site',
            }),
            shell_auth=auth,
            session_id=sid,
        ))

    def test_locale_keys_are_synced_and_compatible_with_android_fallback_yaml_parser(self):
        zh_text = (ROOT / 'locales' / 'zh_CN.yaml').read_text(encoding='utf-8')
        en_text = (ROOT / 'locales' / 'en.yaml').read_text(encoding='utf-8')
        with mock.patch.object(locales, 'yaml', None):
            zh_data = locales._load_yaml(zh_text)
            en_data = locales._load_yaml(en_text)

        shell_keys = [k for k in zh_data if k.startswith('android_shell_')]
        en_shell_keys = [k for k in en_data if k.startswith('android_shell_')]
        self.assertEqual(sorted(shell_keys), sorted(en_shell_keys))
        self.assertGreaterEqual(len(shell_keys), 15)
        for key in shell_keys:
            zh_placeholders = sorted(re.findall(r'\{(\w+)\}', str(zh_data[key])))
            en_placeholders = sorted(re.findall(r'\{(\w+)\}', str(en_data[key])))
            self.assertEqual(zh_placeholders, en_placeholders, msg=f'Placeholder mismatch for {key}')


class AndroidLocalResetHttpTest(_IsolatedDbMixin, AsyncHTTPTestCase):
    def setUp(self):
        self._setup_isolated_db(user_name='admin', raw_password='old-password')
        self.shell_auth = androidShell.ShellAuthManager(boot_token='test-boot-token-value')
        super().setUp()

    def get_app(self):
        return Application([
            (r'/__shell_auth__', androidShell.ShellAuthHandler),
            (r'/__reset_password__', androidShell.LocalPasswordResetHandler),
            (r'/', _ShellIndexHandler),
        ], shell_auth=self.shell_auth, log_function=androidShell.safe_log_request)

    def _authenticate_shell_webview(self, accept_language='zh-CN'):
        auth_resp = self.fetch(
            f'/__shell_auth__?token={self.shell_auth.boot_token}',
            follow_redirects=False,
        )
        self.assertEqual(auth_resp.code, 302)
        self.assertEqual(auth_resp.headers.get('Location'), '/')
        set_cookie = auth_resp.headers.get('Set-Cookie', '')
        self.assertIn('HttpOnly', set_cookie)
        self.assertIn('SameSite=Strict', set_cookie)
        cookie = SimpleCookie()
        cookie.load(set_cookie)
        session_id = cookie[androidShell.SHELL_COOKIE_NAME].value

        page_resp = self.fetch(
            '/',
            headers={
                'Cookie': f'{androidShell.SHELL_COOKIE_NAME}={session_id}',
                'Accept-Language': accept_language,
            },
        )
        self.assertEqual(page_resp.code, 200)
        body = page_resp.body.decode('utf-8')
        match = re.search(r'var T="([^"]+)";', body)
        self.assertIsNotNone(match)
        return session_id, match.group(1), page_resp

    def test_authenticated_shell_webview_can_reset_password_and_never_logs_plaintext_or_tokens(self):
        session_id, csrf_token, page_resp = self._authenticate_shell_webview('zh-CN')
        self.assertEqual(page_resp.headers.get('X-Frame-Options'), 'DENY')
        self.assertEqual(page_resp.headers.get('Content-Security-Policy'), "frame-ancestors 'none'")
        self.assertEqual(page_resp.headers.get('Cache-Control'), 'no-store')
        self.assertEqual(page_resp.headers.get('Referrer-Policy'), 'no-referrer')

        origin = f'http://127.0.0.1:{self.get_http_port()}'
        with self.assertLogs(level='INFO') as captured:
            response = self.fetch(
                '/__reset_password__',
                method='POST',
                body='',
                headers={
                    'Cookie': f'{androidShell.SHELL_COOKIE_NAME}={session_id}',
                    'X-TaoSync-Local': '1',
                    'X-TaoSync-Shell-Token': csrf_token,
                    'Origin': origin,
                    'Sec-Fetch-Site': 'same-origin',
                    'Accept-Language': 'zh-CN',
                },
            )
        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers.get('Cache-Control'), 'no-store')
        self.assertEqual(response.headers.get('X-Frame-Options'), 'DENY')
        payload = json.loads(response.body.decode('utf-8'))
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['userName'], 'admin')
        new_password = payload['password']
        self.assertEqual(len(new_password), 8)

        logged_in = userService.checkPwd(None, new_password, 'admin', clientKey='127.0.0.1')
        self.assertEqual(logged_in['userName'], 'admin')

        combined_logs = '\n'.join(captured.output)
        self.assertIn('admin', combined_logs)
        self.assertNotIn(new_password, combined_logs)
        self.assertNotIn(self.shell_auth.boot_token, combined_logs)
        self.assertNotIn(session_id, combined_logs)
        self.assertNotIn(csrf_token, combined_logs)

    def test_other_local_apps_and_browsers_cannot_auth_scrape_or_reset_password(self):
        old_hash = userMapper.getPrimaryUser()['passwd']

        # Direct GET / without app shell cookie returns minimal blank placeholder, never tokens or UI
        unauth_page = self.fetch('/')
        self.assertEqual(unauth_page.code, 200)
        self.assertEqual(unauth_page.headers.get('X-Frame-Options'), 'DENY')
        self.assertEqual(unauth_page.headers.get('Content-Security-Policy'), "frame-ancestors 'none'")
        self.assertEqual(unauth_page.body.decode('utf-8'), androidShell.UNAUTH_PLACEHOLDER_HTML)
        self.assertNotIn('__reset_password__', unauth_page.body.decode('utf-8'))

        # Wrong boot token rejected, and query string is NOT logged by safe_log_request
        with self.assertLogs('tornado.access', level='WARNING') as access_logs:
            bad_auth = self.fetch('/__shell_auth__?token=attacker-guess-token', follow_redirects=False)
        self.assertEqual(bad_auth.code, 403)
        self.assertNotIn('attacker-guess-token', '\n'.join(access_logs.output))

        # Direct local HTTP client mimicking another Android app with X-TaoSync-Local: 1 is rejected
        other_app_resp = self.fetch(
            '/__reset_password__',
            method='POST',
            body='',
            headers={
                'X-TaoSync-Local': '1',
                'Accept-Language': 'en-US',
            },
        )
        self.assertEqual(other_app_resp.code, 403)
        self.assertEqual(other_app_resp.headers.get('Cache-Control'), 'no-store')
        self.assertIn('local shell', json.loads(other_app_resp.body.decode('utf-8'))['error'].lower())

        # GET /__reset_password__ rejected 405
        self.assertEqual(self.fetch('/__reset_password__', method='GET').code, 405)

        # Even with valid cookie, missing/wrong CSRF token or cross-origin Origin is rejected
        session_id, csrf_token, _ = self._authenticate_shell_webview('en-US')
        missing_csrf = self.fetch(
            '/__reset_password__',
            method='POST',
            body='',
            headers={
                'Cookie': f'{androidShell.SHELL_COOKIE_NAME}={session_id}',
                'X-TaoSync-Local': '1',
            },
        )
        self.assertEqual(missing_csrf.code, 403)

        cross_origin = self.fetch(
            '/__reset_password__',
            method='POST',
            body='',
            headers={
                'Cookie': f'{androidShell.SHELL_COOKIE_NAME}={session_id}',
                'X-TaoSync-Local': '1',
                'X-TaoSync-Shell-Token': csrf_token,
                'Origin': 'http://127.0.0.1:8023',
            },
        )
        self.assertEqual(cross_origin.code, 403)

        userMapper.users = {}
        self.assertEqual(userMapper.getPrimaryUser()['passwd'], old_hash)

    def test_reset_endpoint_reports_persistence_errors_cleanly(self):
        session_id, csrf_token, _ = self._authenticate_shell_webview('zh-CN')
        with mock.patch.object(userService, 'resetPrimaryPasswd', side_effect=RuntimeError('db locked')):
            response = self.fetch(
                '/__reset_password__',
                method='POST',
                body='',
                headers={
                    'Cookie': f'{androidShell.SHELL_COOKIE_NAME}={session_id}',
                    'X-TaoSync-Local': '1',
                    'X-TaoSync-Shell-Token': csrf_token,
                },
            )
        self.assertEqual(response.code, 500)
        payload = json.loads(response.body.decode('utf-8'))
        self.assertFalse(payload['ok'])
        self.assertIn('db locked', payload['error'])

    def test_authenticated_shell_index_serves_localized_html_with_no_store(self):
        _, _, response = self._authenticate_shell_webview('en-US,en;q=0.9')
        self.assertEqual(response.code, 200)
        self.assertEqual(response.headers.get('Cache-Control'), 'no-store')
        body = response.body.decode('utf-8')
        self.assertIn('<html lang="en">', body)
        self.assertIn('Reset Password', body)


if __name__ == '__main__':
    unittest.main()
