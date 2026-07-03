# OPPO/ColorOS 后台保活关键代码说明

本文档提炼 taoSync 在 OPPO(ColorOS)上实现后台保活的关键代码与配置，方便复用到其他 p4a(buildozer webview bootstrap)项目。

## 一、核心思路：主进程 + 服务进程分离

OPPO 后台冻结针对的是**前台 Activity 进程**（PythonActivity）。保活的关键是把业务逻辑放到**独立的服务进程**（:pythonservice），主进程被冻结/杀掉后，服务进程仍能继续运行并提供服务。

```
PythonActivity（主进程）        ←  易被 ColorOS 冻结
   │
   │ start_service_not_as_foreground
   ▼
PythonService（:pythonservice）  ←  前台服务进程，不易被冻结
   │
   ├── 业务 Tornado（如 8023，0.0.0.0）
   └── 日记/调试 Tornado（如 8024，127.0.0.1）
```

- 主进程职责：启动服务、等待端口、加载 WebView、保持 Activity 存活。
- 服务进程职责：运行所有业务逻辑（Tornado server、定时任务等），作为前台服务常驻。

p4a 的 `PythonService` 天然运行在独立进程 `:pythonservice`，是这套方案的基础。

## 二、buildozer.spec 关键配置

```ini
# bootstrap 必须是 webview（service 才能独立进程运行）
p4a.bootstrap = webview

# 权限：前台服务 + 唤醒锁 + 电池优化白名单请求
android.permissions = INTERNET,...,WAKE_LOCK,FOREGROUND_SERVICE,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS

# 唤醒锁：防止 CPU 进入深度睡眠导致服务停滞
android.wakelock = True
```

要点：
- `FOREGROUND_SERVICE`：服务进程作为前台服务运行的必要权限。
- `WAKE_LOCK` + `android.wakelock = True`：保持 CPU 唤醒，服务进程不被深度睡眠挂起。
- `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`：代码里请求电池优化白名单时需要。

## 三、主进程关键代码（main_android.py）

### 1. 启动后台服务（非前台通知方式）

```python
PythonActivity.start_service_not_as_foreground('', '', '')
```

- `start_service`（p4a 默认）内部 `showForegroundNotification=true`，即使标题/描述为空也会显示状态栏常驻通知。
- `start_service_not_as_foreground`（`showForegroundNotification=false`）彻底不显示通知栏通知，但服务进程**仍是前台服务**（FOREGROUND_SERVICE 权限下），保活强度不变。

OPPO 上状态栏常驻通知会显得突兀，故选 `not_as_foreground`。若其他项目保活优先级高于 UI 干净，可改用 `start_service` 走带通知的前台服务，抗杀性更强。

### 2. 等待服务进程端口就绪

```python
def _wait_port(host, port, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (OSError, socket.error):
            time.sleep(0.5)
    return False
```

服务进程启动需要时间（Python 初始化 + 业务模块导入 + Tornado listen）。主进程必须等端口可连后再加载 WebView，否则 WebView 拿到空白页。

### 3. 请求电池优化白名单（代码可自动弹窗）

```python
from jnius import autoclass, cast
Settings = autoclass('android.provider.Settings')
Uri = autoclass('android.net.Uri')
Intent = autoclass('android.content.Intent')
pm = cast('android.os.PowerManager',
          activity.getSystemService(Context.POWER_SERVICE))
pkg = activity.getPackageName()
if not pm.isIgnoringBatteryOptimizations(pkg):
    intent = Intent()
    intent.setAction(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
    intent.setData(Uri.parse('package:' + pkg))
    activity.startActivity(intent)
```

安装后首次启动会自动弹系统对话框，用户确认即可。**注意：OPPO 的「自启动管理」无法通过代码请求/授权，必须用户手动开**（见第五节）。

### 4. 主进程保持存活

```python
# 主流程跑完后不能退出，否则 Activity 可能被销毁
threading.Event().wait()
```

主进程退出会导致 Activity 销毁，虽然服务进程仍在，但 WebView 没了。必须用 `threading.Event().wait()` 让主线程常驻。

## 四、服务进程关键代码（service/main.py）

### 1. 路径与工作目录设置

```python
_app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)
os.chdir(_app_dir)
```

p4a 的 PythonService 运行在独立进程，`sys.path` 与工作目录不会自动设置，必须显式把 app 目录加入 path 并 chdir，否则业务模块 import 失败、相对路径读不到资源。

### 2. 服务进程不退出

```python
try:
    asyncio.run(main())
except Exception as e:
    # 记录日志
    os._exit(1)
```

p4a PythonService 直接执行此文件（不通过 `__main__`）。服务进程若退出，整个应用的后台能力丧失。异常必须捕获并记录，避免静默崩溃。

### 3. 业务端口绑定 0.0.0.0

```python
business_app.listen(port, address='0.0.0.0')
```

OPPO 冻结主进程不影响服务进程，但端口必须监听 `0.0.0.0` 才能让外部设备（浏览器/其他 App）在后台时仍能访问。仅本机用的调试页绑定 `127.0.0.1`。

## 五、OPPO ColorOS 系统手动配置清单（代码无法替代）

代码层面的保活做完后，OPPO 用户必须手动配置以下系统项，否则仍会被冻杀。**换包名后这些授权全部失效，需重新配置**（OPPO 按包名记录授权）。

| 配置项 | 路径（ColorOS） | 作用 |
|---|---|---|
| 自启动管理 | 设置 → 应用管理 → 自启动管理 → 目标App → 开启 | **最关键**。不开则退后台很快被杀，代码无法请求 |
| 电池优化白名单 | 设置 → 电池 → 更多 → 耗电保护 → 目标App → 关闭后台冻结 | 代码会自动弹窗请求，也可手动设 |
| 应用启动管理 | 设置 → 电池 → 更多电池设置 → 应用启动管理 → 目标App → 关闭自动管理 → 手动全开三项 | 自启动/关联启动/后台活动 |
| 任务列表锁定 | 最近任务列表 → 下拉App卡片 → 上锁 | 运行时即时保活 |
| 睡眠待机优化 | 设置 → 电池 → 更多 → 睡眠待机优化 → 目标App → 移除 | ColorOS 12+，防止夜间清理 |

## 六、验证方法

1. 打开 App，进入主界面/WebView 页。
2. 按 Home 键退到后台。
3. 等待 10~30 分钟（OPPO 冻结周期）。
4. 用浏览器访问 `http://<手机IP>:<业务端口>/`，能打开说明服务进程未被冻结，保活生效。
5. 查看日志（`/storage/emulated/0/Android/data/<包名>/files/` 下）是否有新的「服务进程启动」时间戳——若有，说明被杀后重启过（保活不稳，需补配置）。

## 七、常见坑

1. **换包名 = 保活授权清零**：包名一变，OPPO 视为全新应用，旧的白名单/自启动授权全部失效。改包名后必须重新走第五节配置。
2. **start_service 仍显示通知**：p4a 的 `start_service` 强制 `showForegroundNotification=true`，要用 `start_service_not_as_foreground` 才能去掉通知。
3. **服务进程 cwd/path 错误**：PythonService 独立进程不继承主进程的 `sys.path` 和 cwd，业务模块 import 会失败，必须显式设置。
4. **端口绑定 127.0.0.1**：业务端口若只绑 127.0.0.1，OPPO 后台时其他设备访问不了。业务端口绑 `0.0.0.0`，仅本机调试页绑 `127.0.0.1`。
5. **自启动白名单无法代码引导**：`REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` 只管电池优化，OPPO 自启动管理是厂商私有，代码无法请求，必须用户手动开。
6. **前台通知 vs UI 干净**：带通知的前台服务抗杀性最强但状态栏有常驻条；`not_as_foreground` 无通知但依赖系统白名单。OPPO 上建议两者结合（手动开自启动 + 无通知前台服务）。
7. **wakelock 必开**：不开 `android.wakelock`，CPU 深度睡眠后服务进程的定时任务/Tornado 会停滞。

## 八、本项目的实现位置

- 主进程保活逻辑：[main_android.py](file:///workspace/main_android.py)（`_run()` 函数）
- 服务进程：[service/main.py](file:///workspace/service/main.py)
- 构建配置：[buildozer.spec](file:///workspace/buildozer.spec)
