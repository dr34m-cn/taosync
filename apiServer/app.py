import argparse
import base64
import hashlib
import hmac
import html
import io
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

import requests
import tornado.ioloop
import tornado.web
import yaml

try:
    import qrcode
except ImportError:  # pragma: no cover - only the standalone service needs it
    qrcode = None


DEFAULT_AUTHORIZE_URL = "https://openapi.alipan.com/oauth/authorize"
DEFAULT_TOKEN_URL = "https://openapi.alipan.com/oauth/access_token"
DEFAULT_SCOPE = "user:base,file:all:read,file:all:write"
DEFAULT_QR_AUTHORIZE_URL = "https://openapi.alipan.com/oauth/authorize/qrcode"
DEFAULT_QR_STATUS_URL = "https://openapi.alipan.com/oauth/qrcode/{sid}/status"


def _validated_url(name, value, allow_loopback_http=False):
    normalized = str(value or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    loopback_http = (
        allow_loopback_http
        and parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    )
    if parsed.scheme != "https" and not loopback_http:
        raise ValueError("{} must use HTTPS".format(name))
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid {}".format(name))
    return normalized


def load_config(path):
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as stream:
        raw = yaml.safe_load(stream) or {}
    server = dict(raw.get("server") or {})
    aliyun = dict(raw.get("aliyun") or {})
    public_base_url = _validated_url(
        "server.public_base_url", server.get("public_base_url"), allow_loopback_http=True
    )
    client_id = str(aliyun.get("client_id") or "").strip()
    client_secret = str(aliyun.get("client_secret") or "").strip()
    signing_secret = str(server.get("signing_secret") or "").strip()
    if not client_id or not client_secret:
        raise ValueError("aliyun.client_id and aliyun.client_secret are required")
    if len(signing_secret) < 32:
        raise ValueError("server.signing_secret must contain at least 32 characters")
    callback_url = str(aliyun.get("callback_url") or "").strip()
    if not callback_url:
        callback_url = public_base_url + "/v1/aliyun/callback"
    callback_url = _validated_url("aliyun.callback_url", callback_url, allow_loopback_http=True)
    return {
        "server": {
            "host": str(server.get("host") or "0.0.0.0"),
            "port": int(server.get("port") or 8030),
            "public_base_url": public_base_url,
            "session_ttl": max(60, min(int(server.get("session_ttl") or 300), 1800)),
            "max_sessions_per_ip": max(1, int(server.get("max_sessions_per_ip") or 10)),
            "trust_proxy_headers": bool(server.get("trust_proxy_headers", False)),
        },
        "aliyun": {
            "client_id": client_id,
            "client_secret": client_secret,
            "authorize_url": _validated_url(
                "aliyun.authorize_url", aliyun.get("authorize_url") or DEFAULT_AUTHORIZE_URL
            ),
            "token_url": _validated_url(
                "aliyun.token_url", aliyun.get("token_url") or DEFAULT_TOKEN_URL
            ),
            "qr_authorize_url": _validated_url(
                "aliyun.qr_authorize_url",
                aliyun.get("qr_authorize_url") or DEFAULT_QR_AUTHORIZE_URL,
            ),
            "qr_status_url": _validated_url(
                "aliyun.qr_status_url", aliyun.get("qr_status_url") or DEFAULT_QR_STATUS_URL
            ),
            "callback_url": callback_url,
            "scope": str(aliyun.get("scope") or DEFAULT_SCOPE).strip(),
            "signing_secret": signing_secret,
        },
    }


def _qr_data_url(value):
    if qrcode is None:
        raise RuntimeError("qrcode and Pillow are required to create authorization QR codes")
    image = qrcode.make(value)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return "data:image/png;base64," + encoded


def _json(response):
    try:
        data = response.json()
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _oauth_error(prefix, response, data):
    message = data.get("message") or data.get("error_description") or data.get("error")
    if not message:
        message = "HTTP {}".format(response.status_code)
    return "{}: {}".format(prefix, message)


class AliyunOAuthClient:
    def __init__(self, config, session=None):
        self.config = config
        self.session = session or requests.Session()

    def authorization_url(self, state):
        query = {
            "client_id": self.config["client_id"],
            "redirect_uri": self.config["callback_url"],
            "scope": self.config["scope"],
            "response_type": "code",
            "state": state,
        }
        return self.config["authorize_url"] + "?" + urlencode(query)

    def exchange_code(self, code):
        return self._token(
            {
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config["callback_url"],
            }
        )

    def create_qr_session(self):
        response = self.session.post(
            self.config["qr_authorize_url"],
            json={
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "scopes": [item for item in self.config["scope"].split(",") if item],
                "width": 480,
                "height": 480,
            },
            timeout=(15, 45),
        )
        data = _json(response)
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        sid = str(payload.get("sid") or "").strip()
        if response.status_code >= 400 or not sid:
            raise RuntimeError(_oauth_error("Aliyun QR authorization failed", response, payload))
        authorization_url = "https://www.aliyundrive.com/o/oauth/authorize?" + urlencode({"sid": sid})
        return {"sid": sid, "authorization_url": authorization_url}

    def qr_status(self, sid):
        url = self.config["qr_status_url"].format(sid=quote(str(sid), safe=""))
        response = self.session.get(url, timeout=(15, 45))
        data = _json(response)
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        if response.status_code >= 400:
            raise RuntimeError(_oauth_error("Aliyun QR status failed", response, payload))
        return {
            "status": str(payload.get("status") or ""),
            "auth_code": str(payload.get("authCode") or payload.get("auth_code") or ""),
        }

    def exchange_qr_code(self, code):
        return self._token(
            {
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "grant_type": "authorization_code",
                "code": code,
            }
        )

    def refresh(self, refresh_token, refresh_proof):
        if not hmac.compare_digest(self._proof(refresh_token), str(refresh_proof or "")):
            raise PermissionError("invalid refresh proof")
        return self._token(
            {
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

    def _token(self, payload):
        response = self.session.post(self.config["token_url"], json=payload, timeout=(15, 45))
        data = _json(response)
        if response.status_code >= 400 or not data.get("access_token"):
            raise RuntimeError(_oauth_error("Aliyun OAuth failed", response, data))
        result = {
            "access_token": str(data["access_token"]),
            "refresh_token": str(data.get("refresh_token") or payload.get("refresh_token") or ""),
            "expires_in": int(data.get("expires_in") or data.get("expire_in") or 7200),
            "token_type": str(data.get("token_type") or "Bearer"),
        }
        if not result["refresh_token"]:
            raise RuntimeError("Aliyun OAuth failed: refresh_token is missing")
        result["refresh_proof"] = self._proof(result["refresh_token"])
        return result

    def _proof(self, refresh_token):
        return hmac.new(
            self.config["signing_secret"].encode("utf-8"),
            str(refresh_token).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()


@dataclass
class AuthSession:
    session_id: str
    state: str
    poll_token: str
    client_ip: str
    created_at: float
    expires_at: float
    status: str = "pending"
    tokens: dict | None = None
    error: str = ""
    claimed: bool = False
    provider_sid: str = ""
    provider_status: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    provider_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class SessionStore:
    def __init__(self, ttl=300, max_sessions_per_ip=10, clock=time.time):
        self.ttl = ttl
        self.max_sessions_per_ip = max_sessions_per_ip
        self.clock = clock
        self.sessions = {}
        self.states = {}
        self.lock = threading.Lock()

    def create(self, client_ip):
        now = self.clock()
        with self.lock:
            self._cleanup_locked(now)
            active = sum(
                1
                for item in self.sessions.values()
                if item.client_ip == client_ip and not item.claimed and item.expires_at > now
            )
            if active >= self.max_sessions_per_ip:
                raise RuntimeError("too many active authorization sessions")
            item = AuthSession(
                session_id=secrets.token_urlsafe(24),
                state=secrets.token_urlsafe(32),
                poll_token=secrets.token_urlsafe(32),
                client_ip=client_ip,
                created_at=now,
                expires_at=now + self.ttl,
            )
            self.sessions[item.session_id] = item
            self.states[item.state] = item.session_id
            return item

    def get(self, session_id, poll_token=None):
        now = self.clock()
        with self.lock:
            self._cleanup_locked(now)
            item = self.sessions.get(session_id)
        if item is None or item.expires_at <= now:
            raise KeyError("authorization session not found or expired")
        if poll_token is not None and not secrets.compare_digest(item.poll_token, str(poll_token)):
            raise PermissionError("invalid authorization session token")
        return item

    def by_state(self, state):
        with self.lock:
            session_id = self.states.get(str(state))
        if not session_id:
            raise KeyError("authorization state not found or expired")
        return self.get(session_id)

    def complete(self, state, tokens):
        item = self.by_state(state)
        with item.lock:
            if item.status != "pending":
                raise RuntimeError("authorization session is already completed")
            item.tokens = dict(tokens)
            item.status = "authorized"
        return item

    def fail(self, state, message):
        item = self.by_state(state)
        with item.lock:
            if item.status == "pending":
                item.status = "error"
                item.error = str(message)[:500]
        return item

    def claim(self, session_id, poll_token):
        item = self.get(session_id, poll_token)
        with item.lock:
            if item.claimed:
                raise KeyError("authorization result was already claimed")
            if item.status == "error":
                raise RuntimeError(item.error or "authorization failed")
            if item.status != "authorized" or not item.tokens:
                return None
            tokens = dict(item.tokens)
            item.tokens = None
            item.claimed = True
        with self.lock:
            self.states.pop(item.state, None)
        return tokens

    def _cleanup_locked(self, now):
        expired = [
            session_id
            for session_id, item in self.sessions.items()
            if item.expires_at <= now or (item.claimed and now - item.created_at > 60)
        ]
        for session_id in expired:
            item = self.sessions.pop(session_id)
            self.states.pop(item.state, None)


class BaseHandler(tornado.web.RequestHandler):
    def initialize(self, oauth, store):
        self.oauth = oauth
        self.store = store

    def set_default_headers(self):
        self.set_header("Cache-Control", "no-store")
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Referrer-Policy", "no-referrer")
        self.set_header("X-Frame-Options", "DENY")
        self.set_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'",
        )
        self.set_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

    def write_json(self, status, data):
        self.set_status(status)
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.finish(json.dumps(data, ensure_ascii=False))

    def json_body(self):
        try:
            value = json.loads(self.request.body or b"{}")
        except (TypeError, ValueError):
            raise tornado.web.HTTPError(400, reason="invalid JSON body")
        if not isinstance(value, dict):
            raise tornado.web.HTTPError(400, reason="JSON body must be an object")
        return value

    def write_error(self, status_code, **kwargs):
        reason = self._reason or "request failed"
        self.write_json(status_code, {"code": status_code, "message": reason})


class HealthHandler(BaseHandler):
    def get(self):
        self.write_json(200, {"status": "ok", "service": "taosync-auth"})


class SessionCreateHandler(BaseHandler):
    def post(self):
        try:
            item = self.store.create(self.request.remote_ip or "unknown")
        except RuntimeError as exc:
            raise tornado.web.HTTPError(429, reason=str(exc))
        mode = "callback"
        try:
            qr_session = self.oauth.create_qr_session()
            authorization_url = qr_session["authorization_url"]
            item.provider_sid = qr_session["sid"]
            mode = "qrcode"
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Aliyun QR endpoint unavailable, using callback flow: %s", exc
            )
            authorization_url = self.oauth.authorization_url(item.state)
        self.write_json(
            201,
            {
                "session_id": item.session_id,
                "poll_token": item.poll_token,
                "status": item.status,
                "authorization_url": authorization_url,
                "qr_code": _qr_data_url(authorization_url),
                "expires_in": max(0, int(item.expires_at - time.time())),
                "poll_interval": 2,
                "mode": mode,
            },
        )


class SessionStatusHandler(BaseHandler):
    async def get(self, session_id):
        token = self.request.headers.get("X-Authorization-Session", "")
        try:
            item = self.store.get(session_id, token)
        except PermissionError as exc:
            raise tornado.web.HTTPError(403, reason=str(exc))
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=str(exc))
        if item.provider_sid and item.status == "pending":
            await tornado.ioloop.IOLoop.current().run_in_executor(
                None, self._advance_qr_session, item
            )
        with item.lock:
            data = {
                "status": item.status,
                "expires_in": max(0, int(item.expires_at - time.time())),
            }
            if item.error:
                data["message"] = item.error
            if item.provider_status:
                data["provider_status"] = item.provider_status
        self.write_json(200, data)

    def _advance_qr_session(self, item):
        with item.provider_lock:
            with item.lock:
                if item.status != "pending":
                    return
            try:
                result = self.oauth.qr_status(item.provider_sid)
                provider_status = result["status"]
                with item.lock:
                    item.provider_status = provider_status
                normalized = provider_status.lower()
                if normalized in {"loginfailed", "failed", "expired", "canceled"}:
                    with item.lock:
                        item.status = "error"
                        item.error = "Aliyun authorization failed or expired"
                    return
                auth_code = result["auth_code"]
                if normalized not in {"loginsuccess", "success"} or not auth_code:
                    return
                tokens = self.oauth.exchange_qr_code(auth_code)
                with item.lock:
                    if item.status == "pending":
                        item.tokens = tokens
                        item.status = "authorized"
            except Exception as exc:
                logging.getLogger(__name__).warning("Aliyun QR status polling failed: %s", exc)


class SessionClaimHandler(BaseHandler):
    def post(self, session_id):
        token = self.request.headers.get("X-Authorization-Session", "")
        try:
            result = self.store.claim(session_id, token)
        except PermissionError as exc:
            raise tornado.web.HTTPError(403, reason=str(exc))
        except KeyError as exc:
            raise tornado.web.HTTPError(404, reason=str(exc))
        except RuntimeError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc))
        if result is None:
            self.write_json(202, {"status": "pending"})
            return
        self.write_json(
            200,
            {"status": "authorized", "client_id": self.oauth.config["client_id"], **result},
        )


class CallbackHandler(BaseHandler):
    async def get(self):
        state = self.get_query_argument("state", "")
        error = self.get_query_argument("error", "")
        if not state:
            raise tornado.web.HTTPError(400, reason="state is required")
        if error:
            message = self.get_query_argument("error_description", error)
            try:
                self.store.fail(state, message)
            except KeyError as exc:
                raise tornado.web.HTTPError(400, reason=str(exc))
            self._finish_page(False, message)
            return
        code = self.get_query_argument("code", "")
        if not code:
            raise tornado.web.HTTPError(400, reason="authorization code is required")
        try:
            tokens = await tornado.ioloop.IOLoop.current().run_in_executor(
                None, self.oauth.exchange_code, code
            )
            self.store.complete(state, tokens)
        except KeyError as exc:
            raise tornado.web.HTTPError(400, reason=str(exc))
        except Exception as exc:
            logging.getLogger(__name__).warning("Aliyun authorization callback failed: %s", exc)
            try:
                self.store.fail(state, "Aliyun authorization failed")
            except KeyError:
                pass
            self._finish_page(False, "Authorization failed. Return to TaoSync and try again.")
            return
        self._finish_page(True, "Authorization completed. You can return to TaoSync.")

    def _finish_page(self, success, message):
        color = "#18864b" if success else "#c0362c"
        title = "Authorization completed" if success else "Authorization failed"
        self.set_header("Content-Type", "text/html; charset=utf-8")
        safe_title = html.escape(title)
        safe_message = html.escape(str(message))
        self.finish(
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>{}</title></head><body style='font-family:system-ui;padding:40px;color:#202124'>"
            "<main style='max-width:520px;margin:auto'><h1 style='color:{}'>{}</h1><p>{}</p></main>"
            "</body></html>".format(safe_title, color, safe_title, safe_message)
        )


class RefreshHandler(BaseHandler):
    async def post(self):
        body = self.json_body()
        refresh_token = str(body.get("refresh_token") or "").strip()
        refresh_proof = str(body.get("refresh_proof") or "").strip()
        if not refresh_token or len(refresh_token) > 8192:
            raise tornado.web.HTTPError(400, reason="refresh_token is required")
        if len(refresh_proof) != 64:
            raise tornado.web.HTTPError(400, reason="refresh_proof is required")
        try:
            result = await tornado.ioloop.IOLoop.current().run_in_executor(
                None, self.oauth.refresh, refresh_token, refresh_proof
            )
        except PermissionError as exc:
            raise tornado.web.HTTPError(403, reason=str(exc))
        except Exception as exc:
            logging.getLogger(__name__).warning("Aliyun token refresh failed: %s", exc)
            raise tornado.web.HTTPError(502, reason="Aliyun token refresh failed")
        self.write_json(200, result)


def make_app(config, oauth=None, store=None):
    oauth = oauth or AliyunOAuthClient(config["aliyun"])
    server = config["server"]
    store = store or SessionStore(
        ttl=server["session_ttl"], max_sessions_per_ip=server["max_sessions_per_ip"]
    )
    args = {"oauth": oauth, "store": store}
    return tornado.web.Application(
        [
            (r"/health", HealthHandler, args),
            (r"/v1/aliyun/sessions", SessionCreateHandler, args),
            (r"/v1/aliyun/sessions/([^/]+)", SessionStatusHandler, args),
            (r"/v1/aliyun/sessions/([^/]+)/claim", SessionClaimHandler, args),
            (r"/v1/aliyun/callback", CallbackHandler, args),
            (r"/v1/aliyun/token/refresh", RefreshHandler, args),
        ],
        debug=False,
    )


def main():
    parser = argparse.ArgumentParser(description="TaoSync public OAuth service")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(args.config)
    app = make_app(config)
    app.listen(
        config["server"]["port"],
        address=config["server"]["host"],
        xheaders=config["server"]["trust_proxy_headers"],
    )
    logging.info(
        "TaoSync OAuth service listening on %s:%s",
        config["server"]["host"],
        config["server"]["port"],
    )
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
