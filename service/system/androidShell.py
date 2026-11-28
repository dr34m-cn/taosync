"""
Android 本地壳页面（127.0.0.1:8024）辅助模块：
- 通过仅本应用 UID 可读的私有令牌文件完成 main_android.py <-> service/main.py 握手
- 为应用内 WebView 签发仅存内存的 HttpOnly + SameSite=Strict 会话 Cookie 与每会话 CSRF 令牌
- 拒绝同机其他 App、外部浏览器以及跨站页面调用壳页面日志与重置密码接口
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hmac
import ipaddress
import json
import logging
import os
import secrets
import tempfile
import threading
from urllib.parse import urlsplit

from tornado.concurrent import run_on_executor
from tornado.web import RequestHandler

from common import LNG, locales
from service.system import userService

SHELL_LOCAL_HEADER = 'X-TaoSync-Local'
SHELL_LOCAL_HEADER_VALUE = '1'
SHELL_TOKEN_HEADER = 'X-TaoSync-Shell-Token'
SHELL_COOKIE_NAME = 'taosync_shell'
SHELL_TOKEN_FILENAME = '.shell_token'
SHELL_I18N_PLACEHOLDER = '/*__SHELL_I18N__*/null'
SHELL_TOKEN_PLACEHOLDER = '/*__SHELL_TOKEN__*/""'
MAX_SHELL_SESSIONS = 16

# 仅在 p4a 引导探活时向未鉴权的 GET / 返回最小空白占位页，不暴露日志、重置按钮或业务 iframe
UNAUTH_PLACEHOLDER_HTML = (
    '<!DOCTYPE html><html><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<style>html,body{margin:0;height:100%;background:#1e1e1e;}</style>'
    '</head><body></body></html>'
)

_SHELL_I18N_KEYS = {
    'navLabel': 'android_shell_nav_label',
    'tabLogs': 'android_shell_tab_logs',
    'tabWeb': 'android_shell_tab_web',
    'logTitle': 'android_shell_log_title',
    'webTitle': 'android_shell_web_title',
    'clear': 'android_shell_clear',
    'resetPassword': 'android_shell_reset_password',
    'resettingPassword': 'android_shell_resetting_password',
    'passwordLabel': 'android_shell_password_label',
    'copyHint': 'android_shell_password_copy_hint',
    'copy': 'android_shell_copy',
    'copied': 'android_shell_copied',
    'copyFailed': 'android_shell_copy_failed',
    'close': 'android_shell_close',
    'resetFailed': 'android_shell_reset_failed',
}


def _write_private_token_file(token_path, token):
    parent = os.path.dirname(os.path.abspath(token_path))
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.shell-token-', dir=parent)
    try:
        if os.name != 'nt':
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(token)
            output.flush()
            os.fsync(output.fileno())
        if os.name != 'nt':
            os.chmod(temporary, 0o600)
        os.replace(temporary, token_path)
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass


class ShellAuthManager:
    """管理 Android 壳 WebView 的进程级启动令牌与内存会话。"""

    def __init__(self, boot_token=None, max_sessions=MAX_SHELL_SESSIONS):
        self._lock = threading.Lock()
        self._boot_token = boot_token or secrets.token_urlsafe(32)
        self._max_sessions = max(1, int(max_sessions))
        self._sessions = OrderedDict()

    @classmethod
    def create_with_token_file(cls, token_path):
        manager = cls()
        _write_private_token_file(token_path, manager.boot_token)
        return manager

    @property
    def boot_token(self):
        return self._boot_token

    def authenticate_boot_token(self, candidate):
        if not isinstance(candidate, str) or not candidate:
            return None
        if not hmac.compare_digest(candidate, self._boot_token):
            return None
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[session_id] = csrf_token
            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)
        return session_id, csrf_token

    def get_csrf_token(self, session_id):
        if not isinstance(session_id, str) or not session_id:
            return None
        with self._lock:
            csrf_token = self._sessions.get(session_id)
            if csrf_token is not None:
                self._sessions.move_to_end(session_id)
            return csrf_token

    def has_valid_session(self, session_id):
        return self.get_csrf_token(session_id) is not None

    def verify_session_csrf(self, session_id, csrf_token):
        if not isinstance(csrf_token, str) or not csrf_token:
            return False
        expected = self.get_csrf_token(session_id)
        if not expected:
            return False
        return hmac.compare_digest(csrf_token, expected)


def apply_shell_security_headers(handler):
    handler.set_header('Cache-Control', 'no-store')
    handler.set_header('X-Frame-Options', 'DENY')
    handler.set_header('Content-Security-Policy', "frame-ancestors 'none'")
    handler.set_header('Referrer-Policy', 'no-referrer')
    handler.set_header('X-Content-Type-Options', 'nosniff')


def safe_log_request(handler):
    """Tornado log_function：仅在非 2xx/3xx 时记录路径，绝不输出查询串中的令牌。"""
    status = handler.get_status()
    if status < 400:
        return
    level = logging.WARNING if status < 500 else logging.ERROR
    logging.getLogger('tornado.access').log(
        level,
        '%d %s %s (%s) %.2fms',
        status,
        handler.request.method,
        handler.request.path,
        handler.request.remote_ip,
        1000.0 * handler.request.request_time(),
    )


def resolve_shell_lang(accept_language=None):
    if accept_language:
        return locales.getOrSetDefaultLang(accept_language)
    if LNG.sysLanguage:
        return locales.getOrSetDefaultLang(LNG.sysLanguage)
    return locales.defaultLang


def get_shell_i18n(lang):
    return {field: locales.t(key, lang) for field, key in _SHELL_I18N_KEYS.items()}


def _js_json(value):
    return json.dumps(value, ensure_ascii=False).replace('</', '<\\/')


def render_log_page_html(template, accept_language=None, csrf_token=''):
    lang = resolve_shell_lang(accept_language)
    html_lang = 'en' if lang == 'en' else 'zh-CN'
    rendered = template.replace('<html lang="zh">', f'<html lang="{html_lang}">', 1)
    rendered = rendered.replace(SHELL_I18N_PLACEHOLDER, _js_json(get_shell_i18n(lang)), 1)
    return rendered.replace(SHELL_TOKEN_PLACEHOLDER, _js_json(csrf_token or ''), 1)


def is_loopback_ip(remote_ip):
    if not remote_ip:
        return False
    try:
        ip = ipaddress.ip_address(str(remote_ip).split('%', 1)[0])
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    ipv4_mapped = getattr(ip, 'ipv4_mapped', None)
    return bool(ipv4_mapped and ipv4_mapped.is_loopback)


def _default_port(scheme):
    return 443 if scheme == 'https' else 80


def is_loopback_host(host):
    if not host:
        return False
    try:
        parsed = urlsplit(f'http://{host}')
        _ = parsed.port
    except ValueError:
        return False
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        return False
    hostname = (parsed.hostname or '').lower()
    if hostname == 'localhost':
        return True
    return is_loopback_ip(hostname)


def _origin_matches_request(origin, request):
    try:
        origin_parts = urlsplit(origin)
        expected_parts = urlsplit(f'{request.protocol}://{request.host}')
        origin_port = origin_parts.port or _default_port(origin_parts.scheme.lower())
        expected_port = expected_parts.port or _default_port(expected_parts.scheme.lower())
    except ValueError:
        return False
    if origin_parts.scheme.lower() not in ('http', 'https'):
        return False
    if origin_parts.username or origin_parts.password:
        return False
    if origin_parts.path != '' or origin_parts.query or origin_parts.fragment:
        return False
    return (
        origin_parts.scheme.lower() == expected_parts.scheme.lower()
        and (origin_parts.hostname or '').lower() == (expected_parts.hostname or '').lower()
        and origin_port == expected_port
    )


def is_allowed_local_reset_request(request, shell_auth=None, session_id=None):
    if shell_auth is None:
        return False
    if not is_loopback_ip(getattr(request, 'remote_ip', None)):
        return False
    if not is_loopback_host(getattr(request, 'host', None)):
        return False
    headers = request.headers
    if headers.get(SHELL_LOCAL_HEADER) != SHELL_LOCAL_HEADER_VALUE:
        return False
    sec_fetch_site = headers.get('Sec-Fetch-Site')
    if sec_fetch_site and sec_fetch_site.strip().lower() != 'same-origin':
        return False
    origin = headers.get('Origin')
    if origin and not _origin_matches_request(origin, request):
        return False
    csrf_token = headers.get(SHELL_TOKEN_HEADER)
    return shell_auth.verify_session_csrf(session_id, csrf_token)


class ShellAuthHandler(RequestHandler):
    def set_default_headers(self):
        apply_shell_security_headers(self)

    def get(self):
        lang = resolve_shell_lang(self.request.headers.get('Accept-Language'))
        shell_auth = self.settings.get('shell_auth')
        if (
            shell_auth is None
            or not is_loopback_ip(self.request.remote_ip)
            or not is_loopback_host(self.request.host)
        ):
            self.set_status(403)
            self.set_header('Content-Type', 'text/plain; charset=utf-8')
            self.write(locales.t('android_shell_local_only', lang))
            return
        token = self.get_query_argument('token', '')
        issued = shell_auth.authenticate_boot_token(token)
        if issued is None:
            self.set_status(403)
            self.set_header('Content-Type', 'text/plain; charset=utf-8')
            self.write(locales.t('android_shell_local_only', lang))
            return
        session_id, _ = issued
        self.set_cookie(
            SHELL_COOKIE_NAME,
            session_id,
            path='/',
            expires_days=None,
            httponly=True,
            samesite='Strict',
        )
        self.redirect('/')


class LocalPasswordResetHandler(RequestHandler):
    executor = ThreadPoolExecutor(1)

    def set_default_headers(self):
        self.set_header('Content-Type', 'application/json; charset=utf-8')
        apply_shell_security_headers(self)

    @run_on_executor
    def _reset_password(self, lang):
        LNG.set_context_lang(lang)
        result = userService.resetPrimaryPasswd()
        logging.getLogger().info(
            locales.t('android_shell_password_reset_log', lang).format(userName=result['userName'])
        )
        return result

    async def post(self):
        lang = resolve_shell_lang(self.request.headers.get('Accept-Language'))
        shell_auth = self.settings.get('shell_auth')
        session_id = self.get_cookie(SHELL_COOKIE_NAME)
        if not is_allowed_local_reset_request(self.request, shell_auth=shell_auth, session_id=session_id):
            self.set_status(403)
            self.write({
                'ok': False,
                'error': locales.t('android_shell_local_only', lang),
            })
            return
        try:
            result = await self._reset_password(lang)
        except Exception as exc:
            logging.getLogger().exception(exc)
            self.set_status(500)
            self.write({
                'ok': False,
                'error': str(exc),
            })
            return
        self.write({
            'ok': True,
            'userName': result['userName'],
            'password': result['passwd'],
        })
