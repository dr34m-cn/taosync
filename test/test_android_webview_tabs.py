import ast
import unittest
from pathlib import Path


SERVICE_MAIN = Path(__file__).resolve().parents[1] / 'service' / 'main.py'
ANDROID_MAIN = Path(__file__).resolve().parents[1] / 'main_android.py'


def _load_log_page_html():
    module = ast.parse(SERVICE_MAIN.read_text(encoding='utf-8'))
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == '_LOG_PAGE_HTML'
               for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError('_LOG_PAGE_HTML was not found')


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
        self.assertIn('PythonActivity.loadUrl(LOG_URL)', source)
        self.assertNotIn('http://localhost:{PORT}/', source)


if __name__ == '__main__':
    unittest.main()
