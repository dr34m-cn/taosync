### Request header

Use the complete key as the `Authorization` header value. No login cookie is needed. The general API key grants administrator access. The job execution key can only run jobs using the request below. Use HTTPS for remote calls and keep keys out of URLs, logs, and source control.

### Run a specific job

Expand a job in **Jobs** to find its **Job ID**. On mobile, the ID is on the job card. Replace `t-xxxx` with your key, and replace the address and job ID `123` with your own:

```bash
curl -X PUT 'http://127.0.0.1:8023/svr/job' \
  -H 'Authorization: t-xxxx' \
  -H 'Content-Type: application/json' \
  --data '{"id":123,"pause":null}'
```

`pause: null` runs the job immediately. Keep the `id` field: omitting it runs **all jobs**. A response with `code: 200` means the request succeeded, not that synchronization has finished. Check the job history for the result.

Invalid, reset, or disabled keys return **HTTP 401**. Update your scripts after resetting a key.
