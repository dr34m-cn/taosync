# TaoSync Public OAuth Service

This standalone Python service keeps Aliyun Drive Open Platform application credentials outside TaoSync instances. It creates short-lived official QR authorization sessions, falls back to the standard OAuth callback flow when needed, returns the result once, and refreshes user tokens. TaoSync still accesses `openapi.alipan.com` directly for all file operations.

## Configure

1. Create an application in the Aliyun Drive Developer Portal.
2. Register `https://auth.example.com/v1/aliyun/callback` as its callback URL.
3. Copy `config.example.yaml` to `config.yaml` and set the public HTTPS URL, app ID, app secret, and a random signing secret of at least 32 characters.
4. Keep `config.yaml` outside source control and readable only by the service account.

## Run

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py --config config.yaml
```

Put the service behind an HTTPS reverse proxy. When `trust_proxy_headers` is enabled, the proxy must replace client forwarding headers and the application port must not be directly public. The health endpoint is `GET /health`. TaoSync users enter this service URL once and then authorize by scanning the QR code. Authorization sessions expire after five minutes by default and token results can be claimed only once.

The service does not proxy file traffic or persist user tokens. It signs a refresh capability with `signing_secret`, so the refresh endpoint rejects a refresh token that was not issued through this service. Rotating the signing secret requires users to authorize again. In-memory sessions are intentionally lost on restart, so users with an authorization page in progress must scan again. For multiple service instances, use sticky routing or replace `SessionStore` with a shared store that preserves the same one-time-claim semantics.
