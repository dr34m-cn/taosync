<p align="center">
  <strong>English</strong> | <a href="./README_ZH.md">简体中文</a>
</p>

<div align="center">
  <a href="https://github.com/dr34m-cn/taosync"><img width="200" alt="TaoSync logo" src="./web/public/logo-200-64.png"/></a>
  <p><em>TaoSync is an automated synchronization tool for OpenList/AList v3+.</em></p>
  <div>
    <a href="https://github.com/dr34m-cn/taosync/blob/main/LICENSE">
      <img src="https://img.shields.io/github/license/dr34m-cn/taosync" alt="License" />
    </a>
    <a href="https://github.com/dr34m-cn/taosync/actions/workflows/build.yml">
      <img src="https://img.shields.io/github/actions/workflow/status/dr34m-cn/taosync/build.yml?branch=main" alt="Build status" />
    </a>
    <a href="https://www.python.org/">
      <img src="https://img.shields.io/badge/backend-python-326c9c.svg" alt="Python" />
    </a>
    <a href="https://vuejs.org/">
      <img src="https://img.shields.io/badge/frontend-vue-42b883.svg" alt="Vue" />
    </a>
    <a href="https://github.com/dr34m-cn/taosync/releases">
      <img src="https://img.shields.io/github/release/dr34m-cn/taosync" alt="Latest version" />
    </a>
    <a href="https://github.com/dr34m-cn/taosync/releases">
      <img src="https://img.shields.io/github/downloads/dr34m-cn/taosync/total?color=%239F7AEA&logo=github" alt="Downloads" />
    </a>
    <a href="https://hub.docker.com/r/dr34m/tao-sync">
      <img src="https://img.shields.io/docker/pulls/dr34m/tao-sync?color=%2348BB78&logo=docker&label=pulls" alt="Docker Hub pulls" />
    </a>
  </div>
</div>

---

Taotao is my daughter's nickname. I'm her dad, and the logo is based on her.

I originally created this project to preserve photos of Taotao as she grows up, hence the name `TaoSync`.

**If you find TaoSync useful, please star the repository. Thank you!** [GitHub](https://github.com/dr34m-cn/taosync) [Gitee](https://gitee.com/dr34m/taosync) [Docker Hub](https://hub.docker.com/r/dr34m/tao-sync)

<details>

<summary>Click to view screenshots</summary>

TaoSync is updated frequently, so these screenshots are for reference only. Refer to the current interface for the latest design.

#### Job Details

![Job details](./README/作业详情.jpg)

#### Engine Management

![Engine list](./README/引擎列表.png)

#### Edit Engine

![Edit engine](./README/引擎编辑.png)

#### Create Job

![Create job](./README/新建作业.jpg)

#### Job List

![Job list](./README/作业列表.png)

#### Task Details

![Task details](./README/任务详情.png)

#### Notification Settings

![Notification settings](./README/通知配置.jpg)

</details>

## Before You Begin

> [!IMPORTANT]
> You must be familiar with [OpenList](https://docs.oplist.org/) before using TaoSync. `OpenList` is not bundled with TaoSync, so you must run a separate `OpenList` instance.

> [!WARNING]
> **Do not expose TaoSync directly to the public internet. You do so at your own risk!**
>
> TaoSync includes some security measures, but absolute security cannot be guaranteed. If external access is necessary, use a strong password and enable `SSL`.

## Use Cases

#### 1. Synchronized Backups

Back up local files to multiple cloud drives, FTP servers, or similar storage services, or synchronize files between multiple cloud drives.

TaoSync can scan specified directories for differences on a schedule. Full sync mode makes the destination match the source, while Add only mode copies only files that exist in the source but not in the destination.

#### 2. Scheduled Downloads

You can create a one-time job by specifying the year, month, day, hour, minute, and second using `cron`. This lets TaoSync automatically download files from a specific cloud drive to local storage during off-peak hours.

## Features

* Free and open source, open to public review, and available on virtually all common platforms
  * windows-amd64
  * windows-arm64
  * darwin-amd64
  * darwin-arm64
  * linux-amd64
  * linux-arm64
  * linux-386
  * linux-arm-v6
  * linux-arm-v7
  * linux-s390x
  * linux-ppc64le
  * Android
* Executables are automatically built and released through [GitHub Actions](https://docs.github.com/en/actions), making the entire build process public and transparent and minimizing the risk of tampered builds
* Ready-to-use Docker image
* Responsive interface for both desktop and mobile devices
* Clean removal: simply delete TaoSync when you no longer need it; it leaves no residual files or dependencies and does not affect other applications
* Login passwords are stored in the database using a one-way hash, and password resets are supported. If you set the initial password through a configuration file or environment variable, protect that configuration carefully
* Runs entirely offline except for connections to AList and never uploads user data
* Comprehensive error handling for stable, reliable, and internally consistent operation. Errors may happen, but crashes never do (or so I think)
* Detailed logging: all errors are recorded
* Engine management: add, delete, edit, and view `OpenList/AList` engines
* Job management: create, delete, enable, disable, edit, and manually run jobs
* Exclusion rules for preventing specified directories or files from being synchronized
* File-size filtering with independently configurable minimum and maximum values
* Three synchronization modes: Add only, Full sync, and Move mode
* Scheduled synchronization by interval, `cron`, or manual invocation
* Real-time visualization of per-file progress, overall progress, synchronization speed, the file currently being synchronized, estimated completion time, and more
* Controllable storage usage: configure retention periods for task records and logs to keep TaoSync's storage footprint within a predictable range
* Notifications through DingTalk group bots or ServerChan after a task succeeds or fails

## Usage

### Start TaoSync

* Standalone executable

Download the executable for your platform from [Releases](https://github.com/dr34m-cn/taosync/releases) and run it directly.

* Docker

```sh
docker run -d --restart=always -p 8023:8023 -v /opt/data:/app/data --name=taoSync dr34m/tao-sync:latest
```

Or use Docker Compose:

```yaml
version: '3.8'

services:
  tao-sync:
    image: dr34m/tao-sync:latest
    container_name: taoSync
    restart: always
    ports:
      - "8023:8023"
    volumes:
      - /opt/data:/app/data
```

Replace `/opt/data` with the directory you want to use. On some NAS devices, such as UGREEN NAS, you can use a relative path, for example `./config:/app/data`.

For instructions on using TaoSync on a UGREEN NAS, see [How to use TaoSync on a UGREEN NAS to synchronize files to multiple cloud drives (Chinese)](https://dr34m.cn/2024/07/newpost-57/). The setup is similar on other NAS devices that support Docker.

### Use TaoSync

Open `http://127.0.0.1:8023`.

The default username is `admin`. If the initial password is configured as `RANDOM`, find the generated password in the logs. If you configured a password manually, use that value to sign in. After signing in, go to Settings and change the password immediately.

> [!NOTE]
> If the password does not appear in the console output, check `data/log/sys_xxx.log` in the same directory. It is usually on the first line.

After signing in, first open Engine Management and create an engine. Then go to Job Management and create a synchronization job.

## Configuration

<details>
<summary>Click to view configuration options</summary>

Configuration precedence: `data/config.ini` > `environment variables` > `default values`. When a higher-priority source is present, all lower-priority sources are **ignored**. Restart TaoSync or its Docker container after changing the configuration.

Example `data/config.ini` file (when present, this file has the **highest priority**):

```ini
[tao]
# Initial administrator password; only used when the database is first created.
# RANDOM or an empty value generates a random password.
password=RANDOM
# Listening port
port=8023
# Login session lifetime in days
expires=2
# Log level: 0-DEBUG, 1-INFO, 2-WARNING, 3-ERROR, 4-CRITICAL.
# Higher values produce fewer logs; 1 or 2 is recommended.
log_level=1
# Console log level; available in v0.2.3 and later. Uses the same levels as above.
console_level=2
# System log retention period in days. Older logs are removed automatically; 0 disables automatic cleanup.
log_save=7
# Task record retention period in days. Older records are removed automatically; 0 disables automatic cleanup.
task_save=0
# Task execution timeout in hours. Set this high enough for large backups to complete.
task_timeout=72
```

This file does not exist by default. To use it, create `config.ini` in the `data` directory next to the TaoSync executable and add the content shown above. The file must use `UTF-8` encoding.

| config.ini    | Docker environment variable | Description | Default |
| ------------- | --------------------------- | ----------- | ------- |
| password      | TAO_PASSWORD                | Initial administrator password; only used when the database is first created. `RANDOM` or an empty value generates a random password. The legacy `TAO_PASSWD` variable is also supported | RANDOM |
| port          | TAO_PORT                    | Listening port | 8023 |
| expires       | TAO_EXPIRES                 | Login session lifetime, in days | 2 |
| log_level     | TAO_LOG_LEVEL               | Log level: 0-DEBUG, 1-INFO, 2-WARNING, 3-ERROR, 4-CRITICAL. Higher values produce fewer logs; 1 or 2 is recommended | 1 |
| console_level | TAO_CONSOLE_LEVEL           | Console log level; available in v0.2.3 and later. Uses the same levels as above | 2 |
| log_save      | TAO_LOG_SAVE                | System log retention period, in days. Older logs are removed automatically; 0 disables automatic cleanup | 7 |
| task_save     | TAO_TASK_SAVE               | Task record retention period, in days. Older records are removed automatically; 0 disables automatic cleanup | 0 |
| task_timeout  | TAO_TASK_TIMEOUT            | Task execution timeout, in hours. Set this high enough for large backups to complete | 72 |
| -             | TZ                          | Time zone | Asia/Shanghai |

</details>

## Development Status

The changelog is available [here](https://github.com/dr34m-cn/taosync/tree/main/doc/changelog).

To try a development build, look for the latest tag containing `dev` or `pre` on [Docker Hub](https://hub.docker.com/r/dr34m/tao-sync) or [Releases](https://github.com/dr34m-cn/taosync/releases), such as `v0.1.0-dev-build0`. Development builds may contain obvious errors or serious bugs and are not recommended for beginners.

### Planned (subject to change or cancellation if implementation proves too difficult; no promises)

* Improve the Windows version, including launch at startup, hidden-window operation, start/stop controls, and more [#13](https://github.com/dr34m-cn/taosync/issues/13)
* Support encrypted synchronization through OpenList [#18](https://github.com/dr34m-cn/taosync/issues/18)
* Support a local engine that does not depend on `OpenList`
* Support encrypted synchronization for the local engine
* Retain the latest N historical versions, with a configurable and potentially unlimited value for N
* Import and export configuration
* One-command scripts to install, update, and uninstall TaoSync on Linux
