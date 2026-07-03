# feat: 新增 Android 客户端支持

## 概述

为 taoSync 新增完整的 Android 客户端支持，采用主进程 + 服务进程分离架构实现 OPPO/ColorOS 后台保活。所有变更均为新增文件，不影响现有桌面端/Docker 构建逻辑。

## 变更内容

| 文件 | 说明 |
|------|------|
| `main_android.py` | Android 主进程入口，负责启动服务、加载 WebView、请求电池优化白名单 |
| `service/main.py` | 服务进程入口，运行业务 Tornado（8023）+ 日记页 Tornado（8024） |
| `buildozer.spec` | Buildozer 构建配置（webview bootstrap、权限、自适应图标、端口） |
| `.github/workflows/buildAndroid.yml` | Android APK 构建 CI，构建完成后自动将 APK 附加到对应版本的 GitHub Release |
| `.github/workflows/buildStaticX.yml` | Linux 多平台静态构建工作流（amd64/arm64/arm32） |
| `logo.png` / `logo_foreground.png` / `logo_background.png` | 应用图标及自适应图标前后景 |
| `doc/OPPO后台保活.md` | OPPO/ColorOS 后台保活方案文档 |

## 核心设计

- **保活架构**：业务逻辑运行在独立服务进程 `:pythonservice`，主进程被冻结后服务进程仍可运行
- **端口拆分**：8023 业务端口监听 `0.0.0.0` 供外部访问，8024 日记页仅绑定 `127.0.0.1` 不对外暴露
- **p4a 版本**：使用 `v2024.01.21`（Python 3.11），避免新版 Python 3.14 的 mutex 崩溃问题
