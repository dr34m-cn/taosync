"""
taoSync Android 主进程入口（PythonActivity）。

职责：
1. 启动前台服务（service/main.py 运行业务 Tornado 8023 + 日记页 Tornado 8024，
   在 :pythonservice 进程）
2. 等待 8024（日记页）就绪
3. WebView 加载日记页 http://127.0.0.1:8024/

业务逻辑（8023）在服务进程后台运行，即使主进程被 ColorOS 冻结，8023 仍可访问。
日记页（8024）仅绑定 127.0.0.1，只供本机 WebView 展示，不对外暴露。
主进程日志仅写文件，用于诊断启动问题。
"""
import os
import sys
import time
import socket
import threading
import warnings

warnings.filterwarnings('ignore', message='.*character detection dependency.*')

# ======================================================================
# 主进程文件日志（仅诊断用，不显示在页面）
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


def _log(level, msg):
    msg = msg.rstrip('\n')
    if not msg:
        return
    if _file_fp:
        try:
            _file_fp.write(f'[主进程][{level}] {msg}\n')
            _file_fp.flush()
        except Exception:
            pass


_log('INFO', '=== taoSync 主进程启动 ===')
_log('INFO', f'Python: {sys.version}')
_log('INFO', f'cwd: {os.getcwd()}')


def _safe_exit(code=0):
    _log('CRITICAL', f'主进程退出 (code={code})')
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
    _log('ERROR', f'未捕获异常:\n{tb}')


sys.excepthook = _excepthook


# ======================================================================
# 等待端口就绪
# ======================================================================
def _wait_port(host, port, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (OSError, socket.error):
            time.sleep(0.5)
    return False


# ======================================================================
# 主流程
# ======================================================================
def _run():
    # 日记页端口（8024，仅 127.0.0.1）；业务端口 8023 在同一服务进程后台运行
    LOG_HOST = '127.0.0.1'
    LOG_PORT = 8024
    LOG_URL = f'http://{LOG_HOST}:{LOG_PORT}/'

    try:
        from jnius import autoclass, cast
        _log('INFO', 'pyjnius 导入成功')
    except ImportError as e:
        _log('ERROR', f'pyjnius 导入失败: {e}')
        _safe_exit(1)
        return

    try:
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Context = autoclass('android.content.Context')
        Build_VERSION = autoclass('android.os.Build$VERSION')

        activity = PythonActivity.mActivity
        if activity is None:
            _log('ERROR', 'PythonActivity.mActivity 为 None')
            _safe_exit(1)
            return
        sdk_int = Build_VERSION.SDK_INT
        _log('INFO', f'获取 Activity 成功，SDK_INT={sdk_int}')

        # 1. 启动后台服务（业务 8023 + 日记页 8024 在服务进程中运行，不显示通知栏通知）
        # 注意：PythonActivity.start_service 内部 showForegroundNotification=true，
        # 即使标题/描述为空仍会显示前台服务通知；必须用 start_service_not_as_foreground
        # （showForegroundNotification=false）才能彻底不显示通知栏通知。
        try:
            PythonActivity.start_service_not_as_foreground('', '', '')
            _log('INFO', '后台服务已启动，等待 8024 就绪...')
        except Exception as e:
            _log('ERROR', f'启动后台服务失败: {e}')
            _safe_exit(1)
            return

        # 2. 等待服务进程的日记页 Tornado 就绪（8024 起来时 8023 也已就绪）
        if _wait_port(LOG_HOST, LOG_PORT, timeout=30):
            _log('INFO', f'8024 已就绪')
        else:
            _log('ERROR', f'8024 在 30 秒内未就绪')
            _safe_exit(1)
            return

        # 3. 请求电池优化白名单（辅助保活）
        try:
            Settings = autoclass('android.provider.Settings')
            Uri = autoclass('android.net.Uri')
            Intent = autoclass('android.content.Intent')
            pm = cast('android.os.PowerManager',
                      activity.getSystemService(Context.POWER_SERVICE))
            pkg = activity.getPackageName()
            if not pm.isIgnoringBatteryOptimizations(pkg):
                _log('INFO', '请求电池优化白名单')
                intent = Intent()
                intent.setAction(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                intent.setData(Uri.parse('package:' + pkg))
                activity.startActivity(intent)
            else:
                _log('INFO', '已在电池优化白名单中')
        except Exception as e:
            _log('ERROR', f'请求电池优化白名单失败: {e}')

        # 4. WebView 加载日记页（8024 的 / 即日记页）
        try:
            PythonActivity.loadUrl(LOG_URL)
            _log('INFO', f'WebView 已加载 {LOG_URL}')
        except Exception as e:
            _log('ERROR', f'WebView 跳转失败: {e}')

        # 5. 清空 WebView 历史栈，彻底阻止右滑/后退返回到 taoSync 业务页
        # p4a webview bootstrap 历史栈为 [_load.html(0), /(1)]，bootstrap 加载
        # http://127.0.0.1:8024/（日记页），之后本脚本再次 loadUrl 同一地址。
        # 这里 loadUrl 后延迟调用 WebView.clearHistory() 清空历史，
        # 使后退键无路可退（走双击退出逻辑）。
        # mWebView 是 PythonActivity 的 protected static 字段，pyjnius 可反射访问。
        try:
            WebView = autoclass('android.webkit.WebView')
            wv = activity.mWebView
            if wv is not None:
                def _clear_history():
                    # clearHistory 必须在当前页（/）加载完成后调用才有效；
                    # 否则会清掉刚加载的日记页。等待页面渲染。
                    time.sleep(1.5)
                    try:
                        wv.clearHistory()
                        _log('INFO', 'WebView 历史栈已清空')
                    except Exception as e:
                        _log('ERROR', f'clearHistory 失败: {e}')
                threading.Thread(target=_clear_history, daemon=True).start()
            else:
                _log('ERROR', 'mWebView 为 None，无法清空历史栈')
        except Exception as e:
            _log('ERROR', f'获取 mWebView 失败: {e}')

    except Exception as e:
        import traceback
        _log('ERROR', f'主流程异常: {traceback.format_exc()}')
        _safe_exit(1)


_run()

# 主进程保持存活（不退出，否则 Activity 可能被销毁）
_log('INFO', '主进程进入等待')
threading.Event().wait()
