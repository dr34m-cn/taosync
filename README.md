<div align="center">
  <a href=""><img width="200px" alt="logo" src="frontend/public/logo-200-64.png"/></a>
  <p><em>TaoSync是一个适用于AList v3的自动化同步工具。</em></p>
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
      <img src="https://img.shields.io/github/release/dr34m-cn/taosync" alt="latest version" />
    </a>
    <a href="https://github.com/dr34m-cn/taosync/releases">
      <img src="https://img.shields.io/github/downloads/dr34m-cn/taosync/total?color=%239F7AEA&logo=github" alt="Downloads" />
    </a>
    <a href="https://hub.docker.com/r/dr34m/tao-sync">
      <img src="https://img.shields.io/docker/pulls/dr34m/tao-sync?color=%2348BB78&logo=docker&label=pulls" alt="DockerHub" />
    </a>
  </div>
</div>

---

桃桃是我女儿的乳名，我是桃桃她爸，这也是本程序的logo。

本程序开发之初，主要是为了保存桃桃成长的照片，故名`taoSync`

**如果好用，请Star！非常感谢！**  [GitHub](https://github.com/dr34m-cn/taosync) [Gitee](https://gitee.com/dr34m/taosync) [DockerHub](https://hub.docker.com/r/dr34m/tao-sync)

<details>

<summary>点击展开截图</summary>

由于更新频繁，截图仅供参考，以实际为准

#### 引擎管理

![引擎列表](README/引擎列表.png)

#### 引擎编辑

![引擎编辑](README/引擎编辑.png)

#### 新建作业

![新建作业](README/新建作业.png)

#### 作业列表

![作业列表](README/作业列表.png)

#### 作业详情（任务列表）

![任务列表](README/任务列表.png)

#### 任务详情

![任务详情](README/任务详情.png)

</details>

## 须知

使用本工具前你必须了解并且会使用[AList](https://github.com/alist-org/alist)；本工具没有集成`AList`，你需要额外启动`AList`

**警告！不要在外网暴露本系统，否则后果自负！**

> 本系统已经做了一定的安全方面的工作，但仍不能保证绝对安全。如确实需要，请务必使用强密码，并使用`SSL`

## 用途举例

#### 1. 同步备份

把本地文件备份到多个网盘或FTP之类的存储，或者在多个网盘之间同步文件等；

可以定时扫描指定目录下文件差异，让目标目录与源目录相同（全同步模式）；或仅新增存在于源目录，却不存在于目标目录的文件（仅新增模式）

#### 2. 定时下载

可以设置一次性任务（`cron`方式设置年月日时分秒，将在指定时间执行一次），可在闲时自动从特定网盘下载文件到本地

## 特性

* 开源免费，几乎支持所有常用平台
  * windows-amd64
  * darwin-amd64
  * darwin-arm64
  * linux-amd64
  * linux-arm64
  * linux-386
  * linux-arm-v6
  * linux-arm-v7
  * linux-s390x
  * linux-ppc64le
* [Github Actions](https://docs.github.com/zh/actions)自动打包与发布构建好的可执行程序，并支持Docker，下载即用
* 干净卸载，不用的时候删掉即可，无任何残留或依赖，不影响系统里其他程序
* 密码加密不可逆，永远不会泄露您的密码，敏感信息均被加密
* 完全离线运行（仅连接AList），永不上传用户隐私
* 完善的错误处理，稳定可靠，逻辑自洽；可能出错，但永不崩溃（我猜的）
* 完善的日志，所有错误都会被记录
* 引擎管理，可以自由增删改查`AList`
* 作业管理，可以新增/删除/启用/禁用/编辑/手动执行作业
* 仅新增与全同步模式
* 定时同步支持间隔或`cron`方式
* 同步进度实时可视化查看与筛选
* 存储可控，合理配置任务记录与日志保留天数，可以控制本程序所占用存储在可控范围内

## 使用方法

<details>
<summary>点击展开使用方法</summary>

### 先启动

* 可执行程序

前往[Release](https://github.com/dr34m-cn/taosync/releases)下载对应平台的可执行程序，直接执行

* docker

```sh
docker run -d --restart=always -p 8023:8023 -v /opt/data:/app/data --name=taoSync dr34m/tao-sync:latest
```

把其中`/opt/data`替换为你实际的目录

在绿联NAS中使用可以参考这里[如何在绿联NAS中使用TaoSync同步我的文件到各个网盘](https://blog.ctftools.com/2024/07/newpost-57/)，在其他支持Docker的NAS中使用大同小异

### 再使用

访问`http://127.0.0.1:8023`

如果你没有修改，默认账号为`admin`，密码请到日志中查看输出，登录后请立即前往系统设置修改密码

> 如果没有显示这个日志，可以到同级目录的`data/log/sys_xxx.log`文件查看，通常在第一行

进入系统后先到`引擎管理`菜单创建引擎，然后前往`作业管理`创建同步作业

</details>

## 配置项

<details>
<summary>点击展开配置项</summary>

配置优先级：`data/config.ini`>`环境变量`>`默认值`；前一个存在，则后边都将被**忽略**。修改配置需重启程序或Docker。

`data/config.ini`文件示例（如该文件存在，则**优先级最高**）

```ini
[tao]
# 运行端口号
port=8023
# 登录有效期，单位天
expires=2
# 日志等级：0-DEBUG，1-INFO，2-WARNING，3-ERROR，4-CRITICAL；数值越大，产生的日志越少，推荐1或2
log_level=1
# 控制台日志等级：适用于v0.2.3及之后版本，与上同
console_level=2
# 系统日志保留天数，该天数之前的日志会自动清理，单位天，0表示不自动清理
log_save=7
# 任务记录保留天数，该天数之前的记录会自动清理，单位天，0表示不自动清理
task_save=0
# 任务执行超时时间，单位小时。一定要设置长一点，以免要备份的东西太多
task_timeout=72
```

上边的文件默认不存在，如需要，您可以手动在程序同级目录的`data`目录下创建`config.ini`，并填入上边的内容。注意，文件应使用`UTF-8`编码

| config.ini    | Docker环境变量    | 描述                                                         | 默认值           |
| ------------- | ----------------- | ------------------------------------------------------------ |---------------|
| port          | TAO_PORT          | 运行端口号                                                   | 8023          |
| expires       | TAO_EXPIRES       | 登录有效期，单位天                                           | 2             |
| log_level     | TAO_LOG_LEVEL     | 日志等级：0-DEBUG，1-INFO，2-WARNING，3-ERROR，4-CRITICAL；数值越大，产生的日志越少，推荐1或2 | 1             |
| console_level | TAO_CONSOLE_LEVEL | 控制台日志等级：适用于v0.2.3及之后版本；与上同               | 2             |
| log_save      | TAO_LOG_SAVE      | 系统日志保留天数，该天数之前的日志会自动清理，单位天，0表示不自动清理 | 7             |
| task_save     | TAO_TASK_SAVE     | 任务记录保留天数，该天数之前的记录会自动清理，单位天，0表示不自动清理 | 0             |
| task_timeout  | TAO_TASK_TIMEOUT  | 任务执行超时时间，单位小时。一定要设置长一点，以免要备份的东西太多 | 72            |
| -             | TZ                | 时区                                                         | Asia/Shanghai |

</details>

## 研发状态

历史记录在[这里](https://github.com/dr34m-cn/taosync/tree/main/doc/changelog)；

如想体验研发中的版本，可以尝试到[DockerHub](https://hub.docker.com/r/dr34m/tao-sync)或[Release](https://github.com/dr34m-cn/taosync/releases)找最新的含`dev`或`pre`的tag，例如`v0.1.0-dev-build0`

### 规划中（随时改变or因太难不做了，概不负责）

* windows版本优化（开机自启，隐藏页面，启动停止等）[#13](https://github.com/dr34m-cn/taosync/issues/13)
* 移动端适配（可能顺便开发个app？）
* 支持本地引擎（不基于`AList`）
* 任务剩余时间预估
* 任务同步速度计算
* 本地引擎支持加密同步
* 保留历史N个版本（N可自定义，可无限）
* 配置导入导出
* 任务整体进度条展示（目前只能展示每个文件的进度条）
* 多语言支持

### 0.2.3（研发中）

* [x] 修复禁用任务后，手动执行显示`无需同步`的问题 [#9](https://github.com/dr34m-cn/taosync/issues/9)
* [x] 增加`低速`选项，在特定情况下可能可以避免访问频率过高导致触发网盘临时禁用的问题 [#6](https://github.com/dr34m-cn/taosync/issues/6)
* [x] 忘记密码重置
* [ ] 排除指定目录或文件不同步 [#10](https://github.com/dr34m-cn/taosync/issues/10)
* [x] 支持控制台日志输出，并增加控制台日志等级配置项
* [x] 修复启动当日日志文件存有其后部分非当天日志的问题
