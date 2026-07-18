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
    <span class="title">taoSync 运行日志</span>
    <button type="button" id="btnClear">清空</button>
  </div>
  <div id="log"></div>
</section>
<section id="viewWeb" class="view" aria-labelledby="tabWeb" role="tabpanel" hidden>
  <iframe id="businessFrame" title="taoSync 网页" data-src="http://127.0.0.1:8023/"></iframe>
</section>
<script>
var lastSeq = 0;
var logEl = document.getElementById('log');
var statusEl = document.getElementById('status');
var tabLogs = document.getElementById('tabLogs');
var tabWeb = document.getElementById('tabWeb');
var viewLogs = document.getElementById('viewLogs');
var viewWeb = document.getElementById('viewWeb');
var businessFrame = document.getElementById('businessFrame');

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

document.getElementById('btnClear').onclick = function() {
  logEl.innerHTML = '';
};

function nearBottom() {
  return logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 80;
}

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function poll() {
  fetch('/__log__?since=' + lastSeq)
    .then(function(r) { return r.json(); })
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
    def get(self):
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        self.write(_LOG_PAGE_HTML)


class LogDataHandler(RequestHandler):
    def get(self):
        since = int(self.get_argument('since', 0))
        with _log_lock:
            entries = [e for e in _log_entries if e['seq'] > since]
            last_seq = _log_seq
        self.set_header('Content-Type', 'application/json')
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
    # 8023：业务接口 + taoSync 前端（0.0.0.0，允许外部设备访问）
    return Application([
        (r"/svr/noAuth/login", systemController.Login),
        (r"/svr/user", systemController.User),
        (r"/svr/language", systemController.Language),
        (r"/svr/alist", jobController.Alist),
        (r"/svr/storage", jobController.Storage),
        (r"/svr/job", jobController.Job),
        (r"/svr/notify", notifyController.Notify),
        (r"/", MainIndex),
        (r"/(.*)", StaticFileHandler,
         {"path": os.path.join(FRONTEND_PATH, "front")})
    ], cookie_secret=server_cfg['passwdStr'])


def make_log_app():
    # 8024：仅日记页（127.0.0.1）。/ 渲染日记页，/__log__ 提供日志数据
    return Application([
        (r"/__log__", LogDataHandler),
        (r"/", LogIndexHandler),
    ])


async def main():
    _file_log('INFO', '服务进程正在初始化...')
    onStart.init()

    cfg = getConfig()
    server_cfg = cfg['server']
    port = int(server_cfg['port'])

    business_app = make_business_app(server_cfg)
    # 8023 业务端口监听 0.0.0.0，允许外部设备访问；服务进程作为前台服务不会被冻结
    business_app.listen(port, address='0.0.0.0')
    _file_log('INFO', f'业务服务已启动: http://0.0.0.0:{port}/')

    # 8024 日记页仅绑定 127.0.0.1，仅供本机 WebView 访问，不对外暴露
    log_app = make_log_app()
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
