"""
taoSync 前台服务入口（运行在 :pythonservice 进程）。

业务程序（Tornado 8023，0.0.0.0）与日记页（Tornado 8024，仅 127.0.0.1）
在此进程同时运行，作为前台服务，避免主进程（PythonActivity）被 ColorOS
冻结后端口不可访问。8024 仅供本机 WebView 加载日记页，不对外暴露。

p4a 的 PythonService 运行在独立进程，sys.path 与工作目录需显式设置。
"""
import os
import sys
import time
import logging
import threading
import asyncio
import warnings

warnings.filterwarnings('ignore', message='.*character detection dependency.*')

# ======================================================================
# 路径设置：服务进程需显式将 app 目录加入 sys.path
# ======================================================================
_app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)
os.chdir(_app_dir)
os.makedirs('data', exist_ok=True)
os.makedirs('data/log', exist_ok=True)

# ======================================================================
# 内存日志缓冲
# ======================================================================
LOG_MAX = 500
_log_lock = threading.Lock()
_log_entries = []
_log_seq = 0


def _append_log(level, msg):
    global _log_seq
    msg = msg.rstrip('\n')
    if not msg:
        return
    with _log_lock:
        _log_seq += 1
        _log_entries.append({
            'seq': _log_seq,
            'ts': time.time(),
            'level': level,
            'msg': msg,
        })
        if len(_log_entries) > LOG_MAX:
            del _log_entries[:len(_log_entries) - LOG_MAX // 2]
    if _file_fp:
        try:
            _file_fp.write(f'[{level}] {msg}\n')
            _file_fp.flush()
        except Exception:
            pass


def _file_log(level, msg):
    msg = msg.rstrip('\n')
    if not msg:
        return
    if _file_fp:
        try:
            _file_fp.write(f'[{level}] {msg}\n')
            _file_fp.flush()
        except Exception:
            pass


class MemoryLogHandler(logging.Handler):
    def emit(self, record):
        _append_log(record.levelname, record.getMessage())


class _StdoutCapture:
    def __init__(self, level):
        self._level = level
        self._buf = ''

    def write(self, text):
        self._buf += text
        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            if line.strip():
                _append_log(self._level, line)

    def flush(self):
        if self._buf.strip():
            _append_log(self._level, self._buf)
        self._buf = ''


# ======================================================================
# 文件日志后备
# ======================================================================
# 候选日志路径，按优先级尝试：
# 1. app 专属外部目录 getExternalFilesDir（无需权限、始终可写、用户可见，
#    路径为 /storage/emulated/0/Android/data/<包名>/files/taosync_debug.log）
# 2. 上面路径的硬编码形式（包名 com.github.taosync），jnius 不可用时兜底
# 3. 应用内部 cwd（始终可写，但需 root 才能查看）
_file_fp = None
_log_paths = []
try:
    from jnius import autoclass
    _ctx = (getattr(autoclass('org.kivy.android.PythonActivity'), 'mActivity', None)
            or getattr(autoclass('org.kivy.android.PythonService'), 'mService', None))
    _d = _ctx.getExternalFilesDir(None) if _ctx is not None else None
    if _d is not None:
        _log_paths.append(os.path.join(str(_d.getAbsolutePath()), 'taosync_debug.log'))
except Exception:
    pass
_log_paths.append('/storage/emulated/0/Android/data/com.github.taosync/files/taosync_debug.log')
_log_paths.append(os.path.join(os.getcwd(), 'debug.log'))
for _log_path in _log_paths:
    try:
        _file_fp = open(_log_path, 'a', buffering=1)
        break
    except Exception:
        pass


class _FileLogHandler(logging.Handler):
    def emit(self, record):
        if _file_fp:
            try:
                _file_fp.write(f'[{record.levelname}] {record.getMessage()}\n')
            except Exception:
                pass


# ======================================================================
# 安装日志收集
# ======================================================================
_file_log('INFO', '=== taoSync 服务进程启动 ===')
_file_log('INFO', f'Python: {sys.version}')
_file_log('INFO', f'app_dir: {_app_dir}')
_file_log('INFO', f'cwd: {os.getcwd()}')

_logger = logging.getLogger()
_logger.addHandler(MemoryLogHandler())
_logger.addHandler(_FileLogHandler())

logging.getLogger('tornado.access').setLevel(logging.WARNING)

sys.stdout = _StdoutCapture('INFO')
sys.stderr = _StdoutCapture('ERROR')


def _safe_exit(code=0):
    _append_log('CRITICAL', f'服务进程退出 (code={code})')
    if _file_fp:
        try:
            _file_fp.flush()
        except Exception:
            pass
    os._exit(code)


sys.exit = _safe_exit


def _excepthook(exc_type, exc_value, exc_tb):
    import traceback
    tb = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _append_log('ERROR', f'未捕获异常:\n{tb}')
    if _file_fp:
        try:
            _file_fp.write(tb)
            _file_fp.flush()
        except Exception:
            pass


sys.excepthook = _excepthook


# ======================================================================
# 业务模块导入
# ======================================================================
from tornado.web import Application, RequestHandler, StaticFileHandler

from common.config import getConfig
from controller import systemController, jobController, notifyController
from service.system import onStart
from service.system.androidShell import (
    LocalPasswordResetHandler,
    SHELL_COOKIE_NAME,
    SHELL_TOKEN_FILENAME,
    ShellAuthHandler,
    ShellAuthManager,
    UNAUTH_PLACEHOLDER_HTML,
    apply_shell_security_headers,
    is_loopback_host,
    is_loopback_ip,
    render_log_page_html,
    safe_log_request,
)
from service.system.httpsListener import HttpsListener


# ======================================================================
# 日志页面
# ======================================================================
_LOG_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>taoSync Android</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
[hidden] { display: none !important; }
html, body { height: 100%; overflow: hidden; }
body {
  background: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Courier New', Consolas, monospace;
  font-size: 12px;
  display: flex;
  flex-direction: column;
}
button { letter-spacing: 0; }
#tabs {
  flex: 0 0 44px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  background: #181818;
  border-bottom: 1px solid #3c3c3c;
}
.tab {
  min-width: 0;
  appearance: none;
  background: transparent;
  color: #a8a8a8;
  border: 0;
  border-bottom: 2px solid transparent;
  font-family: system-ui, sans-serif;
  font-size: 14px;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.tab.active {
  background: #252526;
  color: #ffffff;
  border-bottom-color: #4ec9b0;
  font-weight: 600;
}
.tab:active { background: #303030; }
.tab:focus { outline: none; }
.view {
  flex: 1 1 auto;
  min-height: 0;
  display: none;
}
.view.active {
  display: flex;
  flex-direction: column;
}
#bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #252526;
  border-bottom: 1px solid #3c3c3c;
}
#bar .title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: bold;
  font-size: 13px;
  flex: 1;
}
#bar button {
  flex-shrink: 0;
  background: #3a3a3a;
  color: #d4d4d4;
  border: 1px solid #3c3c3c;
  border-radius: 3px;
  padding: 5px 12px;
  font-size: 11px;
  cursor: pointer;
}
#bar button:active { background: #505050; }
#bar button:disabled { opacity: 0.6; cursor: wait; }
#bar button.primary {
  background: #234740;
  color: #e6fffb;
  border-color: #4ec9b0;
}
#bar button.primary:active { background: #2c5b52; }
#pwdBanner {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  background: #232a29;
  border-bottom: 1px solid #3c3c3c;
  border-left: 3px solid #4ec9b0;
  font-family: system-ui, sans-serif;
}
#pwdBanner.error {
  background: #2f2020;
  border-left-color: #f44747;
}
.pwd-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.pwd-meta {
  min-width: 0;
  flex: 1;
}
.pwd-label {
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  word-break: break-word;
}
#pwdBanner.error .pwd-label { color: #ff8e8e; }
.pwd-hint {
  margin-top: 2px;
  color: #a8a8a8;
  font-size: 11px;
}
.pwd-hint.ok { color: #4ec9b0; }
.pwd-hint.err { color: #f44747; }
.pwd-close {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  background: transparent;
  color: #a8a8a8;
  border: 1px solid transparent;
  border-radius: 3px;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}
.pwd-close:active { background: #3a3a3a; color: #ffffff; }
.pwd-action-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pwd-code {
  flex: 1;
  min-width: 0;
  padding: 8px 12px;
  background: #181818;
  color: #ffffff;
  border: 1px solid #4ec9b0;
  border-radius: 4px;
  font-family: 'Courier New', Consolas, monospace;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-align: center;
  word-break: break-all;
  cursor: pointer;
  user-select: all;
  -webkit-user-select: all;
  -webkit-tap-highlight-color: transparent;
}
.pwd-code:active { background: #202a28; }
.pwd-copy {
  flex-shrink: 0;
  min-width: 64px;
  padding: 9px 14px;
  background: #4ec9b0;
  color: #111111;
  border: 0;
  border-radius: 4px;
  font-family: system-ui, sans-serif;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}
.pwd-copy:active { background: #3eb59d; }
.pwd-copy.copied {
  background: #2e8b57;
  color: #ffffff;
}
#status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4ec9b0;
  flex-shrink: 0;
}
#status.offline { background: #f44747; }
#log {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 6px 10px;
  -webkit-overflow-scrolling: touch;
}
.line {
  white-space: pre-wrap;
  word-break: break-all;
  padding: 1px 0;
  line-height: 1.6;
}
.line .ts { color: #858585; }
.line .lv { font-weight: bold; margin: 0 4px; }
.lv-DEBUG .lv { color: #569cd6; }
.lv-INFO .lv { color: #4ec9b0; }
.lv-WARNING .lv { color: #dcdcaa; }
.lv-ERROR { color: #f44747; }
.lv-CRITICAL { color: #569cd6; }
.lv-ERROR .lv { color: #f44747; }
.lv-CRITICAL .lv { color: #569cd6; }
#viewWeb { background: #ffffff; }
#businessFrame {
  flex: 1;
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  border: 0;
  background: #ffffff;
}
</style>
</head>
<body>
<nav id="tabs" role="tablist" aria-label="taoSync 页面">
  <button type="button" id="tabLogs" class="tab active" aria-selected="true" aria-controls="viewLogs" role="tab">日志</button>
  <button type="button" id="tabWeb" class="tab" aria-selected="false" aria-controls="viewWeb" role="tab">网页</button>
</nav>
<section id="viewLogs" class="view active" aria-labelledby="tabLogs" role="tabpanel">
  <div id="bar">
    <span id="status"></span>
    <span class="title" id="logTitle">taoSync 运行日志</span>
    <button type="button" id="btnResetPwd" class="primary">重置密码</button>
    <button type="button" id="btnClear">清空</button>
  </div>
  <div id="pwdBanner" role="status" aria-live="polite" hidden>
    <div class="pwd-row">
      <div class="pwd-meta">
        <div id="pwdLabel" class="pwd-label"></div>
        <div id="pwdHint" class="pwd-hint"></div>
      </div>
      <button type="button" id="btnClosePwd" class="pwd-close" aria-label="关闭">&times;</button>
    </div>
    <div id="pwdActionRow" class="pwd-action-row">
      <code id="pwdValue" class="pwd-code" role="button" tabindex="0"></code>
      <button type="button" id="btnCopyPwd" class="pwd-copy">复制</button>
    </div>
  </div>
  <div id="log"></div>
</section>
<section id="viewWeb" class="view" aria-labelledby="tabWeb" role="tabpanel" hidden>
  <iframe id="businessFrame" title="taoSync 网页" data-src="http://127.0.0.1:8023/"></iframe>
</section>
<script>
var SHELL_I18N = /*__SHELL_I18N__*/null;
var SHELL_RESET_TOKEN = /*__SHELL_TOKEN__*/"";
var I18N = {
  navLabel: 'taoSync 页面',
  tabLogs: '日志',
  tabWeb: '网页',
  logTitle: 'taoSync 运行日志',
  webTitle: 'taoSync 网页',
  clear: '清空',
  resetPassword: '重置密码',
  resettingPassword: '重置中...',
  passwordLabel: '新密码（{userName}）',
  copyHint: '点击密码或复制按钮即可复制',
  copy: '复制',
  copied: '已复制',
  copyFailed: '复制失败，请长按手动复制',
  close: '关闭',
  resetFailed: '重置密码失败：{error}'
};
if (SHELL_I18N) {
  for (var _k in SHELL_I18N) {
    if (Object.prototype.hasOwnProperty.call(SHELL_I18N, _k)) {
      I18N[_k] = SHELL_I18N[_k];
    }
  }
}

var lastSeq = 0;
var logEl = document.getElementById('log');
var statusEl = document.getElementById('status');
var tabsEl = document.getElementById('tabs');
var tabLogs = document.getElementById('tabLogs');
var tabWeb = document.getElementById('tabWeb');
var viewLogs = document.getElementById('viewLogs');
var viewWeb = document.getElementById('viewWeb');
var businessFrame = document.getElementById('businessFrame');
var logTitleEl = document.getElementById('logTitle');
var btnClear = document.getElementById('btnClear');
var btnResetPwd = document.getElementById('btnResetPwd');
var pwdBanner = document.getElementById('pwdBanner');
var pwdLabel = document.getElementById('pwdLabel');
var pwdHint = document.getElementById('pwdHint');
var pwdActionRow = document.getElementById('pwdActionRow');
var pwdValue = document.getElementById('pwdValue');
var btnCopyPwd = document.getElementById('btnCopyPwd');
var btnClosePwd = document.getElementById('btnClosePwd');
var currentPassword = '';
var resettingPassword = false;
var copyResetTimer = null;

function fmt(tpl, vars) {
  return String(tpl).replace(/\{(\w+)\}/g, function(_, key) {
    return Object.prototype.hasOwnProperty.call(vars, key) ? String(vars[key]) : '';
  });
}

function applyShellI18n() {
  tabsEl.setAttribute('aria-label', I18N.navLabel);
  tabLogs.textContent = I18N.tabLogs;
  tabWeb.textContent = I18N.tabWeb;
  logTitleEl.textContent = I18N.logTitle;
  businessFrame.setAttribute('title', I18N.webTitle);
  btnClear.textContent = I18N.clear;
  btnResetPwd.textContent = I18N.resetPassword;
  btnCopyPwd.textContent = I18N.copy;
  btnClosePwd.setAttribute('aria-label', I18N.close);
  pwdValue.setAttribute('aria-label', I18N.copy);
  pwdValue.setAttribute('title', I18N.copyHint);
}

applyShellI18n();

function selectView(name) {
  var showWeb = name === 'web';
  tabLogs.classList.toggle('active', !showWeb);
  tabWeb.classList.toggle('active', showWeb);
  tabLogs.setAttribute('aria-selected', String(!showWeb));
  tabWeb.setAttribute('aria-selected', String(showWeb));
  viewLogs.classList.toggle('active', !showWeb);
  viewWeb.classList.toggle('active', showWeb);
  viewLogs.hidden = showWeb;
  viewWeb.hidden = !showWeb;
  if (name === 'web' && !businessFrame.getAttribute('src')) {
    businessFrame.setAttribute('src', businessFrame.dataset.src);
  }
}

tabLogs.onclick = function() { selectView('logs'); };
tabWeb.onclick = function() { selectView('web'); };

btnClear.onclick = function() {
  logEl.innerHTML = '';
};

function clearCopyTimer() {
  if (copyResetTimer !== null) {
    clearTimeout(copyResetTimer);
    copyResetTimer = null;
  }
}

function fallbackCopyText(text) {
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.setAttribute('inputmode', 'none');
  ta.style.position = 'fixed';
  ta.style.top = '-9999px';
  ta.style.left = '-9999px';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  try {
    ta.focus({ preventScroll: true });
  } catch (e) {
    ta.focus();
  }
  ta.select();
  ta.setSelectionRange(0, text.length);
  var ok = false;
  try {
    ok = document.execCommand('copy');
  } catch (e) {
    ok = false;
  }
  document.body.removeChild(ta);
  return ok;
}

function copyText(text) {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    return navigator.clipboard.writeText(text).then(function() {
      return true;
    }).catch(function() {
      return fallbackCopyText(text);
    });
  }
  return Promise.resolve(fallbackCopyText(text));
}

function selectPasswordNode() {
  if (!window.getSelection || !document.createRange) return;
  try {
    var range = document.createRange();
    range.selectNodeContents(pwdValue);
    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  } catch (e) {}
}

function copyCurrentPassword() {
  if (!currentPassword) return;
  clearCopyTimer();
  copyText(currentPassword).then(function(ok) {
    if (ok) {
      btnCopyPwd.textContent = I18N.copied;
      btnCopyPwd.classList.add('copied');
      pwdHint.textContent = I18N.copied;
      pwdHint.className = 'pwd-hint ok';
      copyResetTimer = setTimeout(function() {
        btnCopyPwd.textContent = I18N.copy;
        btnCopyPwd.classList.remove('copied');
        pwdHint.textContent = I18N.copyHint;
        pwdHint.className = 'pwd-hint';
        copyResetTimer = null;
      }, 2000);
    } else {
      selectPasswordNode();
      pwdHint.textContent = I18N.copyFailed;
      pwdHint.className = 'pwd-hint err';
    }
  });
}

function showPasswordResult(userName, password) {
  clearCopyTimer();
  currentPassword = password;
  pwdBanner.classList.remove('error');
  pwdActionRow.hidden = false;
  pwdLabel.textContent = fmt(I18N.passwordLabel, { userName: userName || 'admin' });
  pwdHint.textContent = I18N.copyHint;
  pwdHint.className = 'pwd-hint';
  pwdValue.textContent = password;
  btnCopyPwd.textContent = I18N.copy;
  btnCopyPwd.classList.remove('copied');
  pwdBanner.hidden = false;
}

function showPasswordError(message) {
  clearCopyTimer();
  currentPassword = '';
  pwdValue.textContent = '';
  pwdBanner.classList.add('error');
  pwdActionRow.hidden = true;
  pwdLabel.textContent = fmt(I18N.resetFailed, { error: message || '' });
  pwdHint.textContent = '';
  pwdHint.className = 'pwd-hint';
  pwdBanner.hidden = false;
}

btnResetPwd.onclick = function() {
  if (resettingPassword) return;
  resettingPassword = true;
  btnResetPwd.disabled = true;
  btnResetPwd.textContent = I18N.resettingPassword;
  function finishReset() {
    resettingPassword = false;
    btnResetPwd.disabled = false;
    btnResetPwd.textContent = I18N.resetPassword;
  }
  fetch('/__reset_password__', {
    method: 'POST',
    credentials: 'same-origin',
    headers: {
      'X-TaoSync-Local': '1',
      'X-TaoSync-Shell-Token': SHELL_RESET_TOKEN
    }
  })
    .then(function(r) {
      return r.json().catch(function() { return {}; }).then(function(data) {
        return { status: r.status, ok: r.ok, data: data };
      });
    })
    .then(function(res) {
      if (res.ok && res.data && res.data.ok && res.data.password) {
        showPasswordResult(res.data.userName, res.data.password);
      } else {
        var msg = (res.data && res.data.error) || ('HTTP ' + res.status);
        showPasswordError(msg);
      }
      finishReset();
    })
    .catch(function(err) {
      showPasswordError(err && err.message ? err.message : String(err));
      finishReset();
    });
};

pwdValue.onclick = copyCurrentPassword;
pwdValue.onkeydown = function(e) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    copyCurrentPassword();
  }
};
btnCopyPwd.onclick = copyCurrentPassword;
btnClosePwd.onclick = function() {
  clearCopyTimer();
  currentPassword = '';
  pwdValue.textContent = '';
  pwdBanner.hidden = true;
};

function nearBottom() {
  return logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 80;
}

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function poll() {
  fetch('/__log__?since=' + lastSeq, { credentials: 'same-origin' })
    .then(function(r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    })
    .then(function(data) {
      statusEl.classList.remove('offline');
      if (data.last_seq) lastSeq = data.last_seq;
      if (!data.entries || data.entries.length === 0) return;
      var scroll = nearBottom();
      data.entries.forEach(function(e) {
        var d = new Date(e.ts * 1000);
        var ts = d.getHours() + ':' +
                 String(d.getMinutes()).padStart(2,'0') + ':' +
                 String(d.getSeconds()).padStart(2,'0');
        var line = document.createElement('div');
        line.className = 'line lv-' + e.level;
        line.innerHTML = '<span class="ts">[' + ts + ']</span>' +
                         '<span class="lv">' + e.level + '</span>' +
                         escapeHtml(e.msg);
        logEl.appendChild(line);
      });
      while (logEl.children.length > 2000) {
        logEl.removeChild(logEl.firstChild);
      }
      if (scroll) logEl.scrollTop = logEl.scrollHeight;
    })
    .catch(function() { statusEl.classList.add('offline'); })
    .finally(function() { setTimeout(poll, 1500); });
}

// 阻止后退键退出 Activity：8024 的 / 即日记页，p4a webview bootstrap
// 加载 http://127.0.0.1:8024/ 后由 main_android.py 再次 loadUrl(/)。
// 这里用带 hash 的 URL（与无 hash 的当前页 URL 不同，确保 pushState
// 生成真实历史项，避免某些 WebView 对同 URL pushState 的优化）压入
// 多个缓冲项，形成较深历史栈；后退触发 popstate 时立即补回缓冲项，
// 使后退键只在日记页内部循环，触发双击退出逻辑而非直接退出。
(function() {
  var n = 0;
  function push() {
    n += 1;
    history.pushState({ i: n }, '', '#stay' + n);
  }
  push(); push(); push();
  window.addEventListener('popstate', function() { push(); });
  window.addEventListener('pageshow', function(e) { if (e.persisted) { push(); push(); } });
})();

poll();
</script>
</body>
</html>"""


class LogIndexHandler(RequestHandler):
    def set_default_headers(self):
        apply_shell_security_headers(self)

    def get(self):
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        shell_auth = self.settings.get('shell_auth')
        csrf_token = None
        if (
            shell_auth is not None
            and is_loopback_ip(self.request.remote_ip)
            and is_loopback_host(self.request.host)
        ):
            csrf_token = shell_auth.get_csrf_token(self.get_cookie(SHELL_COOKIE_NAME))
        if not csrf_token:
            self.write(UNAUTH_PLACEHOLDER_HTML)
            return
        self.write(
            render_log_page_html(
                _LOG_PAGE_HTML,
                self.request.headers.get('Accept-Language'),
                csrf_token=csrf_token,
            )
        )


class LogDataHandler(RequestHandler):
    def set_default_headers(self):
        apply_shell_security_headers(self)

    def get(self):
        shell_auth = self.settings.get('shell_auth')
        if (
            shell_auth is None
            or not is_loopback_ip(self.request.remote_ip)
            or not is_loopback_host(self.request.host)
            or not shell_auth.has_valid_session(self.get_cookie(SHELL_COOKIE_NAME))
        ):
            self.set_status(403)
            self.set_header('Content-Type', 'application/json; charset=utf-8')
            self.write({'entries': [], 'last_seq': 0})
            return
        since = int(self.get_argument('since', 0))
        with _log_lock:
            entries = [e for e in _log_entries if e['seq'] > since]
            last_seq = _log_seq
        self.set_header('Content-Type', 'application/json; charset=utf-8')
        self.write({'entries': entries, 'last_seq': last_seq})


# ======================================================================
# 业务应用
# ======================================================================
FRONTEND_PATH = _app_dir


class MainIndex(RequestHandler):
    def get(self):
        # 8023 业务前端入口：直接渲染 taoSync 前端页面。
        # 日记页已拆分到 8024（仅 127.0.0.1），由 Android WebView 单独加载，
        # 浏览器访问 8023 不受影响。
        with open(os.path.join(FRONTEND_PATH, "front", "index.html"),
                  'r', encoding='utf-8') as f:
            html = f.read()
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        self.write(html)


# 日记页专用端口：仅绑定 127.0.0.1，供 Android WebView 加载，不对外暴露
LOG_PORT = 8024


def make_business_app(server_cfg):
    from controller.updateController import UpdateCheck, UpdateInfo, UpdateReleases
    # 8023：业务接口 + taoSync 前端（0.0.0.0，允许外部设备访问）
    return Application([
        (r"/svr/noAuth/login", systemController.Login),
        (r"/svr/user", systemController.User),
        (r"/svr/settings", systemController.Settings),
        (r"/svr/settings/https", systemController.Https),
        (r"/svr/settings/api-key", systemController.ApiKey),
        (r"/svr/settings/update", UpdateInfo),
        (r"/svr/settings/update/check", UpdateCheck),
        (r"/svr/settings/update/releases", UpdateReleases),
        (r"/svr/language", systemController.Language),
        (r"/svr/alist", jobController.Alist),
        (r"/svr/storage", jobController.Storage),
        (r"/svr/job", jobController.Job),
        (r"/svr/job/links", jobController.JobLinks),
        (r"/svr/notify", notifyController.Notify),
        (r"/", MainIndex),
        (r"/(.*)", StaticFileHandler,
         {"path": os.path.join(FRONTEND_PATH, "front")})
    ], cookie_secret=server_cfg['passwdStr'])


def make_log_app(shell_auth):
    # 8024：仅日记页（127.0.0.1），仅限携带本应用私有握手会话的 WebView 访问
    return Application([
        (r"/__shell_auth__", ShellAuthHandler),
        (r"/__log__", LogDataHandler),
        (r"/__reset_password__", LocalPasswordResetHandler),
        (r"/", LogIndexHandler),
    ], shell_auth=shell_auth, log_function=safe_log_request)


async def main():
    _file_log('INFO', '服务进程正在初始化...')
    onStart.init()

    cfg = getConfig()
    server_cfg = cfg['server']
    port = int(server_cfg['port'])

    business_app = make_business_app(server_cfg)
    # 8023 业务端口监听 0.0.0.0，允许外部设备访问；服务进程作为前台服务不会被冻结
    business_app.listen(port, address='0.0.0.0')
    https = business_app.settings['https_listener'] = HttpsListener(business_app, address='0.0.0.0', http_port=port)
    https.restore()
    _file_log('INFO', f'业务服务已启动: http://0.0.0.0:{port}/')

    # 在监听 8024 前写入仅本应用 UID 可读的握手令牌，供 main_android.py 认证壳 WebView
    shell_auth = ShellAuthManager.create_with_token_file(
        os.path.join(_app_dir, 'data', SHELL_TOKEN_FILENAME)
    )
    # 8024 日记页仅绑定 127.0.0.1，仅供本机应用内 WebView 访问，不对外暴露
    log_app = make_log_app(shell_auth)
    log_app.listen(LOG_PORT, address='127.0.0.1')
    _file_log('INFO', f'日记页已启动: http://127.0.0.1:{LOG_PORT}/')

    logger = logging.getLogger()
    logger.critical(f'启动成功_/_Running at http://127.0.0.1:{port}/ (业务), http://127.0.0.1:{LOG_PORT}/ (日记)')

    await asyncio.Event().wait()


# p4a PythonService 直接执行此文件，不通过 __main__
try:
    asyncio.run(main())
except Exception as e:
    import traceback
    tb = traceback.format_exc()
    _append_log('ERROR', f'服务进程启动失败:\n{tb}')
    if _file_fp:
        try:
            _file_fp.write(tb)
            _file_fp.flush()
        except Exception:
            pass
    os._exit(1)
