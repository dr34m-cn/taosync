# 2026-11-05 代码审查遗留问题清单

本文记录 2026-11-05 全项目审查中**尚未修复**的问题，供后续排期。同一轮审查中已修复的问题在文末列出，便于对照。

每条包含：位置、问题、影响和建议。严重程度分为 高、中、低。

---

## 一、同步核心

### 1. 启动加载作业失败时会永久删除作业（中）

- **位置**：`service/syncJob/jobClient.py` 中 `JobClient.__init__` 的异常分支（`isInit or addJobId != 0`）。
- **问题**：启动时（`isInit=True`），只要 `doByTime` 抛出异常，`jobMapper.deleteJob` 就会把作业、全部历史任务和源目录快照一并删掉。比如 APScheduler 升级后 cron 校验变严，或数据库中的 cron 字段异常。
- **影响**：升级或配置异常后，用户的作业和历史记录会静默丢失，且无法恢复。
- **建议**：启动阶段只记录错误，并把作业标记为禁用或异常状态，不删除数据。仅在新增作业失败时回滚刚插入的行。

### 2. AList 客户端未复用 HTTP 连接（低）

- **位置**：`service/alist/alistClient.py` 中的 `AlistClient.req`。
- **问题**：每个请求都调用 `requests.request` 新建连接。扫描大目录时请求密集；进行中的复制最多 20 个，每个都在高频轮询状态。
- **建议**：改用 `requests.Session`（每个客户端一个，或每线程一个）复用连接。

### 3. 源目录模式不检测目标侧被手动删除的文件（设计取舍，低）

- **位置**：`JobTask.syncFromSourceSnapshot`。
- **问题**：源目录模式只比较源目录的前后快照，不扫描目标目录。用户在目标侧手动删除的文件，只要源文件没有变化，就不会被重新复制。
- **建议**：在界面和文档中说明这一点，或提供"强制全量比对一次"的入口。

---

## 二、存储驱动与内置引擎

### 4. 阿里云盘驱动没有路径到 file_id 的缓存（中，性能）

- **位置**：`service/storage/drivers/aliyun.py`（路径解析、`_assert_file_destination`、`_remove_duplicates`）和 `service/engine/taosyncClient.py`。
- **问题**：每次操作都要逐级列出祖先目录来解析路径；一次复制要重复列目标目录多次。全局限速约每秒 3.9 次列目录，并且被 20 个复制线程共享。
- **影响**：向同一个大目录同步上千个文件时，单是列目录就要花几个小时。
- **建议**：增加带 TTL 的 `path → file_id` 缓存，写操作后定点失效。合并同一次复制中的重复列目录。

### 5. 阿里云上传 `complete` 超时重试可能误删已上传的文件（中）

- **位置**：`service/storage/drivers/aliyun.py` 中 `openFile/complete` 的重试逻辑，以及 `_abort_upload`。
- **问题**：第一次 `complete` 实际已经成功、只是响应超时的话，重试失败后会走 `_abort_upload`，把刚完成的新文件删掉。
- **建议**：重试前先查询目标文件状态。确认已完成则视为成功，不要中止上传。

### 6. SFTP 未配置主机指纹时接受任意主机密钥（中，安全）

- **位置**：`service/storage/drivers/sftp.py`，主机密钥校验相关逻辑。
- **问题**：指纹为空时，每次连接都接受任意密钥，而不只是首次连接。指纹只有在前端点击"测试"时才会填入。
- **影响**：遭遇中间人攻击时，密码或密钥认证会发送给攻击者，且没有任何提示。
- **建议**：首次连接时记录指纹（TOFU，首次信任），之后指纹不一致就拒绝连接；或者把保存时提供指纹设为必填。

### 7. SFTP 和 FTP 每次操作都重新建立连接（低到中，性能）

- **位置**：`sftp.py` 中 `list`、`download`、`upload` 等操作，以及 `ftp.py`。
- **问题**：每次操作都要重新完成 TCP、SSH 或 FTP 握手并登录；SFTP 还会逐级 `lstat` 根路径；FTP 上传会开两个连接。
- **影响**：扫描大目录树又慢，又容易触发服务端的登录频率限制或 fail2ban。
- **建议**：为每个挂载建立带空闲超时的连接池，并缓存根路径的校验结果。

### 8. FTP 和 SFTP 的路径身份包含用户名，与 SMB 不一致（低）

- **位置**：`service/storage/pathIdentity.py`。
- **问题**：同一主机、同一路径、不同用户名的两个挂载，会被判定为不重叠，从而绕过全同步删除前的源目标重叠保护。
- **建议**：用于判断重叠的身份应只看主机、端口和路径，不看用户名。

### 9. 通过 API 把挂载设为 `enabled=0` 后，它会从界面消失（低）

- **位置**：`mapper/storageMapper.py` 中的 `getMountList`（只返回 `enabled=1`），以及 `storageService.updateMount`。
- **问题**：禁用的挂载在界面上看不到，也无法重新启用。之后还能创建一个同名挂载，再启用旧挂载就会出现两个同名挂载。
- **建议**：列表接口返回所有挂载并标出禁用状态；名称唯一性校验也要包含已禁用的挂载。

---

## 三、通知

### 10. 企业微信凭据会写进日志（中，安全）

- **位置**：`service/notify/notifyService.py`。
- **问题**：`corpid`、`corpsecret` 和 `access_token` 通过字符串拼接放进 URL 查询串，没有编码。网络异常时，异常信息里会带上完整 URL，并被写进日志和测试结果。
- **建议**：改用 `requests` 的 `params=` 传参，并在记录异常前做脱敏处理。

### 11. 自定义 Webhook 只把 HTTP 200 当作成功（中）

- **位置**：`notifyService.py`，`if r.status_code != 200`。
- **问题**：返回 201 或 204 的服务（比如 Discord 返回 204）明明已经送达，却每次都被报错。
- **建议**：把所有 2xx 都视为成功。

### 12. `GET /svr/notify` 返回明文密钥（低）

- **位置**：`controller/notifyController.py` 和 `mapper/notifyMapper.py`。
- **问题**：`sendKey`、`corpsecret` 以及带 token 的 Webhook URL 都原样返回给前端。存储挂载已经做了脱敏，通知还没有。
- **建议**：参照存储挂载的 `secretState` 机制做脱敏，编辑时沿用已保存的值。

### 13. 自定义 Webhook 可以访问内网地址（低，SSRF）

- **位置**：`notifyService.py`，自定义 Webhook 发送逻辑。
- **问题**：URL 不受限制，会跟随重定向；非 200 响应时还会把响应体原样显示在测试结果里，等于可以用来读取内网 HTTP 服务的内容。
- **建议**：测试结果里不回显响应体，或只显示截断后的内容。可选再加一项"禁止私有地址"的开关。

---

## 四、公共 OAuth 服务（apiServer）

### 14. 按 IP 限制会话数依赖 `remote_ip`（低）

- **位置**：`apiServer/app.py` 中的 `SessionStore.create` 调用，以及 `trust_proxy_headers`。
- **问题**：部署在反向代理后面又没有开启信任代理头时，所有用户都显示为同一个 IP，整个服务最多只能有 10 个并发会话。开启信任代理头、但端口又直接暴露在外时，可以伪造 `X-Forwarded-For` 绕过限制。
- **建议**：在部署文档中写明代理配置要求；可以考虑再加一个全局会话上限。

### 15. 回调先换取 token，再校验 state（低）

- **位置**：`apiServer/app.py` 中的 `CallbackHandler`。
- **问题**：任何人请求 `GET /v1/aliyun/callback?state=x&code=y`，都会先触发一次带 `client_secret` 的上游 token 请求，之后才校验 state 是否存在。
- **建议**：先校验 state 存在且处于 pending 状态，再去换取 token。

### 16. 授权轮询把长期凭据下发给浏览器（低）

- **位置**：`service/storage/aliyunAuth.py` 中的 `poll`。
- **问题**：`refresh_token`、`refresh_proof` 和 `access_token` 会经过浏览器，再由 `addMount` 提交回来，因此会留在浏览器内存、开发者工具和代理日志里。
- **建议**：凭据只保存在服务端，按授权会话句柄关联，`addMount` 时只提交句柄。

### 17. `apiServer/Dockerfile` 以 root 运行，基础镜像版本未固定（低）

---

## 五、前端

### 18. 路径选择器关闭后会残留上次的选择（中）

- **位置**：`web/src/views/pages/home/components/pathSelect.vue`。
- **问题**：`cuPath` 只在 `closeShow()` 中重置；通过右上角 X 或 Esc 关闭对话框时，它不会被清空。
- **影响**：下次打开选择器时可以直接点确定，把上次选的路径（比如源目录）加成另一个字段，例如目标目录。
- **建议**：在 `show()` 中重置 `cuPath`，或者监听对话框关闭事件来重置。

### 19. 跨过 768px 断点会丢失未保存的作业表单（中低）

- **位置**：`web/src/views/pages/home/index.vue` 的 `v-if` 切换，`task.vue` 和 `taskDetail.vue` 也一样。
- **问题**：桌面端和移动端是两个独立组件，`editData` 是各自的局部状态，切换时组件被卸载，表单内容随之丢失。比如 iPad 横竖屏旋转。
- **建议**：把编辑状态提升到 Pinia store 或父组件，或者在切换前提示用户。

### 20. 桌面端与移动端作业表单逻辑已不一致（低）

- **排除规则去重**：桌面端 `addExclude` 不去重，移动端会去重。规则还被当作 `v-for` 的 key，重复时会出警告并可能更新错行。
- **空段处理**：桌面端用 `split(":")` 拆分 `dstPath` 和 `exclude` 时不过滤空段，会保存出空规则。
- **引擎列表加载失败**：移动端 `await ensureAlistList()` 没有 catch，加载失败时编辑框打不开，还会产生未处理的 Promise 拒绝。
- **建议**：把表单的解析和校验抽成 `web/src/utils` 下的共享函数，并补充单元测试。

### 21. 会话过期弹窗点"取消"后会反复弹出（中低）

- **位置**：`web/src/utils/request.js`。
- **问题**：点取消后，后台轮询仍在继续，每次请求返回 401 都会再弹一次。另外，请求错误处理里 `Promise.reject(error)` 前少了 `return`。
- **建议**：用户取消后，暂停轮询或在一段时间内不再弹窗，并补上 `return`。

### 22. 列表请求没有处理乱序返回（低）

- **位置**：`desktop.vue`、`mobile.vue`、`taskDesktop.vue`、`taskMobile.vue` 中的列表加载函数。
- **问题**：快速翻页时，较晚返回的旧响应会覆盖新页的数据，表现为页码是 3、内容却是第 2 页。
- **建议**：参照引擎页的做法，加请求序号守卫。

### 23. 体积与性能（低）

- **ECharts 全量引入**：只用于两个饼图，所在 chunk 达 1.14MB。改为按需引入。
- **Element Plus 图标全部全局注册**：入口 chunk 达 1.33MB。
- **实时进度轮询**：每 610ms 一次，不判断标签页是否可见；每次 `setOption(..., true)` 都会让动画重新开始。
- **重复资源**：`src/assets/images/login-bg.jpg` 与 `assets/img/login-bg.jpg` 内容完全相同，前者未被使用。

### 24. 其他前端问题（低）

- `engine/index.vue` 约 2400 行，建议按驱动拆成子组件和组合式函数。
- 任务相关页面的返回按钮用 `router.go(-1)`；通过深链接或新标签页打开时，点返回会离开应用。
- eslint 报错：`pathSelect.vue:32` 有未使用的变量 `err`。

---

## 六、构建与发布

### 25. CI 不运行测试和 lint（中）

- **位置**：`.github/workflows/build.yml`。
- **问题**：发布前不跑 `python -m unittest`、`npm run test` 和 eslint，也没有针对 PR 的工作流。
- **建议**：先加一个运行测试和 lint 的 job，构建与发布的 job 依赖它通过后再执行。

### 26. 生产镜像以 root 运行，且没有 HEALTHCHECK（中）

- **位置**：根目录 `Dockerfile`。
- **建议**：增加非 root 用户并处理好 `/app/data` 的权限；增加请求 `/` 的 `HEALTHCHECK`。

### 27. 构建上下文几乎没有过滤（低）

- **位置**：`.dockerignore` 中只有 `wheels/`。
- **问题**：本地构建时，`.git`、`venv`、`web/node_modules`、`data/`（含数据库和 token）都会被送进构建上下文。`COPY . /app` 在 `pip install` 之前，任何源码改动都会让依赖层缓存失效。
- **建议**：补全 `.dockerignore`，并调整层顺序，先复制依赖清单再复制源码。

### 28. 基础镜像链不可复现（低到中）

- **版本未固定**：各 `dockerfiles/*.Dockerfile` 中 pip 和 PyInstaller 都没有固定版本。
- **不会自动更新**：基础镜像只在自身 Dockerfile 变化时重建，拿不到 Alpine 和 Python 的安全更新。
- **不会级联**：`python` 镜像重建后，`pyinstaller` 和 `pip-req` 不会跟着重建；最终镜像引用的是可变的 `not-for-use-*` 标签。
- **缓存残留**：`apk add` 没有使用 `--no-cache`。

### 29. Actions 和依赖版本未固定（低）

- **Actions**：用的是标签而不是 SHA，包括拥有 release 写权限的第三方 `softprops/action-gh-release@v2`。没有声明工作流级别的 `permissions:`。
- **构建缓存**：七平台的 QEMU 构建没有使用 `cache-from` 和 `cache-to`。
- **安卓依赖**：`buildozer.spec` 中的依赖没有锁版本，也没有列出 `PyYAML`；安卓端会改用后备的 YAML 解析器。
- **前端依赖**：`vue-i18n` 9.x 可能已停止维护；锁文件中 `js-yaml` 4.1.0 有原型污染公告（4.1.1 已修复，仅开发依赖）。这两条需要联网确认。

---

## 附：本轮已修复的问题

1. 扫描间隔限速失效：引入共享的 `common/intervalGate.py` 按根目录均匀排队，AList 和内置引擎同时生效。
2. `task_timeout` 配置不生效：ini 读取正确的键名（兼容旧的 `timeout`），任务超过设定时长后按超时（状态 5）中止。
3. 复制状态轮询遇到一次网络错误就判失败：改为连续失败 5 次才判失败，404 仍立即判失败。
4. `copyHook` 和 `delHook` 的 `createTime` 默认值在导入时就固定了：改为调用时取值，并写入 `job_task_item`。
5. 任务内部队列存在多线程竞争：加锁保护，等待队列改用 `deque`。
6. 中止后只等 2 秒就入库：改为有限时间内等待取消完成；仍未结束的复制按失败记录一次，之后到达的回调不再重复记录。
7. 每个作业各建一个调度器：改为全局共用一个 `BackgroundScheduler`，禁用的作业以暂停状态加入。
8. `sqlBase` 的锁不是原子的：改为 `threading.RLock`，并保留原始异常类型。
9. 缺少常用查询索引：启动时幂等创建 `job_task_item(taskId)` 和 `job_task(jobId, createTime)` 索引。
10. 登录安全：
    - 密码哈希改为 PBKDF2，旧的 MD5 哈希登录成功后自动升级。
    - Cookie 中只存会话版本，不再存密码摘要，并加上 `HttpOnly` 和 `SameSite=Lax`。
    - 密码错误次数改为按 IP 或用户分别限制。
    - 重置密钥使用常量时间比较；随机数改用 `secrets`。
11. apiServer 创建二维码会话时阻塞事件循环：改为放到线程池执行。
12. 编辑挂载时，地址或账号改了仍沿用已保存的密钥：
    - 阿里云：client_id、api_url 或 oauth_url 变化时，必须重新填写密钥或重新扫码。
    - SMB 和 FTP：主机、端口或用户名变化时，必须重新输入密码。
    - SMB 共享发现：目标主机不同时，不再使用已保存的密码。
