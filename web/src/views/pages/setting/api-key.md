### 请求头

将 64 位密钥原样放入 `Authorization` 请求头，无需登录 Cookie，也不要添加 `Bearer` 前缀。密钥拥有管理员权限；远程调用请使用 HTTPS，不要把密钥放入 URL、日志或代码仓库。

### 执行指定作业

在「作业管理」展开目标作业，查看 **作业ID**；手机端可直接在作业卡片上查看。下面的示例使用 Bash 和 curl。请先安全设置环境变量 `TAOSYNC_API_KEY`，再将地址和示例 ID `123` 替换为实际值：

```bash
curl -X PUT 'http://127.0.0.1:8023/svr/job' \
  -H "Authorization: $TAOSYNC_API_KEY" \
  -H 'Content-Type: application/json' \
  --data '{"id":123,"pause":null}'
```

`pause: null` 表示立即执行。请保留 `id`：省略它会执行所有作业。响应中的 `code: 200` 表示请求成功，不代表同步已完成；执行结果请查看作业历史。

密钥错误、已重置或已禁用时，接口返回 **HTTP 401**。重置后请更新脚本中的密钥。
