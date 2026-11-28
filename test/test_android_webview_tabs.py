import ast
import json
import unittest
from pathlib import Path

from service.system.androidShell import (
    SHELL_I18N_PLACEHOLDER,
    SHELL_TOKEN_PLACEHOLDER,
    render_log_page_html,
)


ROOT = Path(__file__).resolve().parents[1]
SERVICE_MAIN = ROOT / 'service' / 'main.py'
ANDROID_MAIN = ROOT / 'main_android.py'
DESKTOP_MAIN = ROOT / 'main.py'


def _load_log_page_html():
    module = ast.parse(SERVICE_MAIN.read_text(encoding='utf-8'))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == '_LOG_PAGE_HTML'
               for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('_LOG_PAGE_HTML was not found')


def _get_function_source(path, func_name):
    source = path.read_text(encoding='utf-8')
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f'{func_name} was not found in {path}')


class AndroidWebViewTabsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _load_log_page_html()

    def test_log_tab_is_the_default_view(self):
        self.assertIn('id="tabLogs" class="tab active"', self.html)
        self.assertIn('id="tabLogs" class="tab active" aria-selected="true"', self.html)
        self.assertIn('id="viewLogs" class="view active"', self.html)
        self.assertIn('id="tabWeb" class="tab" aria-selected="false"', self.html)
        self.assertIn('id="viewWeb" class="view"', self.html)

    def test_web_tab_targets_the_local_business_page(self):
        self.assertIn('data-src="http://127.0.0.1:8023/"', self.html)
        self.assertNotIn('target="_blank"', self.html)
        self.assertNotIn('window.open(', self.html)

    def test_business_page_is_loaded_lazily_inside_the_shell(self):
        self.assertIn("if (name === 'web' && !businessFrame.getAttribute('src'))", self.html)
        self.assertIn("businessFrame.setAttribute('src', businessFrame.dataset.src);", self.html)
        self.assertIn("tabLogs.onclick = function() { selectView('logs'); };", self.html)
        self.assertIn("tabWeb.onclick = function() { selectView('web'); };", self.html)

    def test_log_shell_uses_the_same_loopback_host_as_the_business_page(self):
        source = ANDROID_MAIN.read_text(encoding='utf-8')
        self.assertIn("LOG_HOST = '127.0.0.1'", source)
        self.assertIn("LOG_PORT = 8024", source)
        self.assertIn("__shell_auth__?token=", source)
        self.assertIn('PythonActivity.loadUrl(auth_url)', source)
        self.assertNotIn('_log(\'INFO\', f\'WebView 已加载 {auth_url}\')', source)
        self.assertNotIn('http://localhost:{PORT}/', source)

    def test_shell_page_exposes_instant_password_reset_and_copy_controls(self):
        self.assertIn('id="btnResetPwd"', self.html)
        self.assertIn('id="pwdBanner"', self.html)
        self.assertIn('id="pwdValue"', self.html)
        self.assertIn('id="btnCopyPwd"', self.html)
        self.assertIn('id="btnClosePwd"', self.html)
        self.assertIn("fetch('/__reset_password__'", self.html)
        self.assertIn("credentials: 'same-origin'", self.html)
        self.assertIn("'X-TaoSync-Local': '1'", self.html)
        self.assertIn("'X-TaoSync-Shell-Token': SHELL_RESET_TOKEN", self.html)
        self.assertIn('navigator.clipboard.writeText', self.html)
        self.assertIn("document.execCommand('copy')", self.html)
        self.assertIn('pwdValue.onclick = copyCurrentPassword;', self.html)
        self.assertIn('btnCopyPwd.onclick = copyCurrentPassword;', self.html)
        self.assertIn(SHELL_I18N_PLACEHOLDER, self.html)
        self.assertIn(SHELL_TOKEN_PLACEHOLDER, self.html)

    def test_reset_route_is_only_registered_on_local_log_app(self):
        log_app_src = _get_function_source(SERVICE_MAIN, 'make_log_app')
        business_app_src = _get_function_source(SERVICE_MAIN, 'make_business_app')
        desktop_src = DESKTOP_MAIN.read_text(encoding='utf-8')
        self.assertIn('/__shell_auth__', log_app_src)
        self.assertIn('ShellAuthHandler', log_app_src)
        self.assertIn('/__reset_password__', log_app_src)
        self.assertIn('LocalPasswordResetHandler', log_app_src)
        self.assertIn('log_function=safe_log_request', log_app_src)
        self.assertNotIn('/__reset_password__', business_app_src)
        self.assertNotIn('/__shell_auth__', business_app_src)
        self.assertNotIn('/__reset_password__', desktop_src)
        self.assertNotIn('/__shell_auth__', desktop_src)

    def test_render_log_page_html_supports_zh_and_en_locales(self):
        zh_html = render_log_page_html(self.html, 'zh-CN,zh;q=0.9', csrf_token='tok-zh')
        en_html = render_log_page_html(self.html, 'en-US,en;q=0.9', csrf_token='tok-en')
        self.assertIn('<html lang="zh-CN">', zh_html)
        self.assertIn('<html lang="en">', en_html)
        self.assertNotIn(SHELL_I18N_PLACEHOLDER, zh_html)
        self.assertNotIn(SHELL_I18N_PLACEHOLDER, en_html)
        self.assertNotIn(SHELL_TOKEN_PLACEHOLDER, zh_html)
        self.assertNotIn(SHELL_TOKEN_PLACEHOLDER, en_html)
        self.assertIn('"tok-zh"', zh_html)
        self.assertIn('"tok-en"', en_html)
        self.assertIn(json.dumps('重置密码', ensure_ascii=False), zh_html)
        self.assertIn(json.dumps('Reset Password', ensure_ascii=False), en_html)
        self.assertIn(json.dumps('Copied', ensure_ascii=False), en_html)


if __name__ == '__main__':
    unittest.main()
