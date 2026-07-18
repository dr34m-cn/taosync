[app]

title = taoSync
package.name = taosync
package.domain = com.github

source.dir = .
source.include_exts = py,png,jpg,jpeg,html,js,css,ttf,otf,svg,ico,json,gif,woff,woff2,map,yaml
source.include_patterns = front/**,locales/**,common/**,controller/**,mapper/**,service/**,doc/config.ini

version = 0.3.2

requirements = python3,pyjnius,android,tornado,requests,urllib3,certifi,chardet,idna,apscheduler,tzlocal,tzdata,setuptools,configparser,pathspec,openssl,sqlite3,cryptography,smbprotocol,paramiko

orientation = portrait
fullscreen = 0
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE,WAKE_LOCK,FOREGROUND_SERVICE,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS

android.api = 33
android.minapi = 21
android.ndk_api = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

android.wakelock = True
android.allow_backup = True
android.apptheme = @android:style/Theme.NoTitleBar
android.presplash_color = #FFFFFF
android.showlog = 0
# buildozer 标准配置项为 icon.filename（android.icon 非标准，会被忽略）
# 要求 512x512 PNG，会自动生成各分辨率 mipmap（legacy 图标，API<26 及文件管理器回退用）
icon.filename = %(source.dir)s/logo.png
# 自适应图标（API>=26）：补全前景/背景，否则 p4a 自动生成的 mipmap-anydpi-v26
# /ic_launcher.xml 引用的图层不完整，导致压缩包/文件管理器解析 APK 时解码失败、
# 回退默认图标（安装后启动器能渲染，故出现“文件里默认、装完才正常”的现象）。
# 前景：logo 缩到安全区(~300px)居中、四周透明；背景：纯白（与 presplash 一致）。
icon.adaptive_foreground.filename = %(source.dir)s/logo_foreground.png
icon.adaptive_background.filename = %(source.dir)s/logo_background.png

p4a.branch = v2024.01.21
p4a.bootstrap = webview
# WebView 启动后加载 8024 日记页（仅 127.0.0.1）；业务前端 8023 在后台服务进程运行
p4a.extra_args = --port=8024

android.release_artifact = apk
android.debug_artifact = apk

log_level = 2

[buildozer]

log_level = 2
warn_on_root = 1

bin_dir = bin
