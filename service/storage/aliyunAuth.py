import secrets
import threading
import time
from urllib.parse import urlparse

import requests

from common.config import getConfig


_sessions = {}
_sessions_lock = threading.Lock()


def _auth_server_url():
    value = str(getConfig()["server"].get("aliyun_auth_server") or "").strip().rstrip("/")
    if not value:
        raise ValueError("Aliyun authorization service is not configured")
    parsed = urlparse(value)
    local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError("Aliyun authorization service must use HTTPS")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("invalid Aliyun authorization service URL")
    return value


def _response_json(response):
    try:
        data = response.json()
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _request_error(prefix, response, data):
    message = data.get("message") or data.get("msg") or data.get("error")
    if not message:
        message = "HTTP {}".format(response.status_code)
    return "{}: {}".format(prefix, message)


def _remote_request(method, url, **kwargs):
    response = requests.request(method, url, timeout=(15, 45), **kwargs)
    data = _response_json(response)
    if response.status_code >= 400:
        raise RuntimeError(_request_error("Aliyun authorization service failed", response, data))
    return data


def _cleanup():
    now = time.time()
    with _sessions_lock:
        for handle in [key for key, item in _sessions.items() if item["expires_at"] <= now]:
            _sessions.pop(handle, None)


def start(engine_id):
    from service.storage.storageService import _requireTaoSync

    _requireTaoSync(int(engine_id))
    _cleanup()
    auth_server = _auth_server_url()
    data = _remote_request("POST", auth_server + "/v1/aliyun/sessions", json={})
    required = ("session_id", "poll_token", "qr_code")
    if any(not data.get(key) for key in required):
        raise RuntimeError("Aliyun authorization service returned an incomplete session")
    expires_in = max(30, min(int(data.get("expires_in") or 300), 1800))
    handle = secrets.token_urlsafe(24)
    with _sessions_lock:
        _sessions[handle] = {
            "engine_id": int(engine_id),
            "auth_server": auth_server,
            "session_id": str(data["session_id"]),
            "poll_token": str(data["poll_token"]),
            "expires_at": time.time() + expires_in,
            "lock": threading.Lock(),
        }
    return {
        "handle": handle,
        "status": "pending",
        "qrCode": data["qr_code"],
        "authorizationUrl": data.get("authorization_url") or "",
        "expiresIn": expires_in,
        "pollInterval": max(1, min(int(data.get("poll_interval") or 2), 10)),
    }


def poll(engine_id, handle):
    _cleanup()
    with _sessions_lock:
        item = _sessions.get(str(handle))
    if item is None or item["engine_id"] != int(engine_id):
        raise ValueError("Aliyun authorization session not found or expired")
    with item["lock"]:
        headers = {"X-Authorization-Session": item["poll_token"]}
        session_url = "{}/v1/aliyun/sessions/{}".format(
            item["auth_server"], item["session_id"]
        )
        status = _remote_request("GET", session_url, headers=headers)
        state = str(status.get("status") or "pending")
        if state == "pending":
            return {"status": state, "expiresIn": int(status.get("expires_in") or 0)}
        if state == "error":
            with _sessions_lock:
                _sessions.pop(str(handle), None)
            raise RuntimeError(status.get("message") or "Aliyun authorization failed")
        if state != "authorized":
            raise RuntimeError("unknown Aliyun authorization status")
        tokens = _remote_request("POST", session_url + "/claim", headers=headers, json={})
        refresh_token = str(tokens.get("refresh_token") or "").strip()
        refresh_proof = str(tokens.get("refresh_proof") or "").strip()
        access_token = str(tokens.get("access_token") or "").strip()
        if not refresh_token or not refresh_proof or not access_token:
            raise RuntimeError("Aliyun authorization service returned incomplete tokens")
        with _sessions_lock:
            _sessions.pop(str(handle), None)
        return {
            "status": "authorized",
            "config": {
                "auth_mode": "service",
                "auth_service_url": item["auth_server"],
                "client_id": str(tokens.get("client_id") or ""),
                "client_secret": "",
                "refresh_token": refresh_token,
                "refresh_proof": refresh_proof,
                "access_token": access_token,
                "expires_at": time.time() + int(tokens.get("expires_in") or 7200),
            },
        }
