import base64
import binascii
import hashlib
import json
import math
import posixpath
import re
import socket
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
from urllib3.connection import HTTPSConnection
from urllib3.connectionpool import HTTPSConnectionPool
from urllib3.util import connection as urllib3_connection

from common.fileFingerprint import fileFingerprint

from .base import StorageDriver, TransferCancelled, check_cancel, child_path, normalize_path


_GLOBAL_RATE_LOCK = threading.Lock()
_GLOBAL_RATE_STATES = {}


class AliyunAPIError(RuntimeError):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.code = code


class _PrefixReader:
    def __init__(self, prefix, source):
        self.prefix = prefix
        self.source = source

    def read(self, size=-1):
        if not self.prefix:
            return self.source.read(size)
        if size is None or size < 0:
            data, self.prefix = self.prefix, b""
            return data + self.source.read()
        data, self.prefix = self.prefix[:size], self.prefix[size:]
        return data


def _sha1(value):
    return value.upper() if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value) else None


def _upload_times(metadata):
    result = {}
    for field in ("created_at", "modified_at"):
        value = metadata.get(field)
        if value is None:
            continue
        try:
            instant = (datetime.fromisoformat(value.replace("Z", "+00:00"))
                       if isinstance(value, str) else datetime.fromtimestamp(value, timezone.utc))
            if instant.tzinfo is None:
                instant = instant.replace(tzinfo=timezone.utc)
            result["local_" + field] = instant.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        except (ValueError, TypeError, OverflowError, OSError):
            continue
    return result


class _UploadHTTPSConnection(HTTPSConnection):
    def _new_conn(self):
        # Some dual-stack Aliyun upload routes accept IPv6 connections but
        # stall while sending parts. Preserve the hostname for TLS and prefer
        # IPv4 only for the upload service; the normal connector is a fallback.
        if self._dns_host.endswith((".aliyundrive.net", ".aliyuncs.com")):
            try:
                addresses = socket.getaddrinfo(
                    self._dns_host, self.port, socket.AF_INET, socket.SOCK_STREAM
                )
            except socket.gaierror:
                addresses = []
            for _family, _kind, _protocol, _name, address in addresses:
                try:
                    sock = urllib3_connection.create_connection(
                        address[:2], self.timeout,
                        source_address=self.source_address,
                        socket_options=self.socket_options,
                    )
                except OSError:
                    continue
                sys.audit("http.client.connect", self, self.host, self.port)
                return sock
        return super()._new_conn()


class _UploadHTTPSConnectionPool(HTTPSConnectionPool):
    ConnectionCls = _UploadHTTPSConnection


class _TransferAdapter(requests.adapters.HTTPAdapter):
    @staticmethod
    def _use_upload_connections(manager):
        manager.pool_classes_by_scheme = {
            **manager.pool_classes_by_scheme,
            "https": _UploadHTTPSConnectionPool,
        }

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        kwargs["blocksize"] = 256 * 1024
        super().init_poolmanager(connections, maxsize, block=block, **kwargs)
        self._use_upload_connections(self.poolmanager)

    def proxy_manager_for(self, proxy, **kwargs):
        kwargs["blocksize"] = 256 * 1024
        return super().proxy_manager_for(proxy, **kwargs)


def _account_key(client_id, refresh_token, drive_id):
    try:
        payload = refresh_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        subject = json.loads(base64.urlsafe_b64decode(payload.encode("ascii"))).get("sub")
        if subject:
            return client_id + ":" + str(subject)
    except (IndexError, ValueError, TypeError, KeyError, json.JSONDecodeError,
            binascii.Error, UnicodeDecodeError):
        pass
    if drive_id:
        return client_id + ":" + drive_id
    return client_id + ":" + hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


class _PartReader:
    def __init__(self, source, length, cancel, on_read):
        self.source = source
        self.length = length
        self.cancel = cancel
        self.on_read = on_read
        self.position = 0
        self.cached = 0
        self.reported = 0
        # Ordinary 20 MiB parts stay in memory. Large parts may spill to disk,
        # but the first attempt starts sending without staging the whole part.
        self.buffer = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024, mode="w+b")

    def __len__(self):
        return self.length

    def tell(self):
        return self.position

    def reset(self):
        self.position = 0

    def close(self):
        self.buffer.close()

    def read(self, size=-1):
        check_cancel(self.cancel)
        remaining = self.length - self.position
        if remaining <= 0:
            return b""
        if size is None or size < 0:
            size = remaining
        size = min(size, remaining)
        if size == 0:
            return b""
        if self.position < self.cached:
            self.buffer.seek(self.position)
            data = self.buffer.read(min(size, self.cached - self.position))
        else:
            data = self.source.read(min(max(size, 1024 * 1024), self.length - self.cached))
            if not data:
                raise IOError("source stream ended before the expected file size")
            self.buffer.seek(self.cached)
            self.buffer.write(data)
            self.cached += len(data)
            data = data[:size]
        self.position += len(data)
        if self.position > self.reported:
            self.on_read(self.position - self.reported)
            self.reported = self.position
        return data


class AliyunDriveDriver(StorageDriver):
    supports_random_read = True
    supports_native_move = True
    """Aliyun Drive Open API driver.

    It uses the public OAuth/OpenFile endpoints rather than private web-client
    APIs. Authentication can use either local application credentials or a
    separately deployed TaoSync OAuth service.
    """

    driver_type = "aliyun"
    API_URL = "https://openapi.alipan.com"
    PART_SIZE = 20 * 1024 * 1024
    MAX_PARTS = 10000

    def __init__(
        self,
        config,
        save_config=None,
        load_config=None,
        refresh_lock=None,
        auth_version=None,
    ):
        self.config = dict(config)
        self.api_url = str(self.config.get("api_url") or self.API_URL).rstrip("/")
        self.oauth_url = str(
            self.config.get("oauth_url") or self.api_url + "/oauth/access_token"
        )
        self.auth_service_url = str(self.config.get("auth_service_url") or "").strip().rstrip("/")
        self.auth_mode = str(self.config.get("auth_mode") or "").strip().lower()
        self.client_id = str(self.config.get("client_id") or "").strip()
        self.client_secret = str(self.config.get("client_secret") or "").strip()
        self.refresh_token = str(self.config.get("refresh_token") or "").strip()
        self.refresh_proof = str(self.config.get("refresh_proof") or "").strip()
        if not self.auth_mode:
            self.auth_mode = "service" if self.auth_service_url and not self.client_secret else "direct"
        if self.auth_mode == "service":
            if not self.auth_service_url or not self.refresh_token or not self.refresh_proof:
                raise ValueError("Aliyun authorization service, refresh_token and refresh_proof are required")
        elif self.auth_mode == "direct":
            if not self.client_id or not self.client_secret or not self.refresh_token:
                raise ValueError("Aliyun client_id, client_secret and refresh_token are required")
        else:
            raise ValueError("invalid Aliyun auth_mode")
        self.access_token = str(self.config.get("access_token") or "")
        self.expires_at = float(self.config.get("expires_at") or 0)
        self.drive_type = str(self.config.get("drive_type") or "resource")
        if self.drive_type not in ("default", "resource", "backup"):
            raise ValueError("invalid Aliyun drive_type")
        self.drive_id = str(self.config.get("drive_id") or "")
        self.root_folder_id = str(self.config.get("root_folder_id") or "root")
        self.remove_way = str(self.config.get("remove_way") or "trash")
        if self.remove_way not in ("trash", "delete"):
            raise ValueError("invalid Aliyun remove_way")
        self.rapid_upload = self.config.get("rapid_upload", True)
        if not isinstance(self.rapid_upload, bool):
            raise ValueError("Aliyun rapid_upload must be a boolean")
        self.save_config = save_config
        self.load_config = load_config
        self.auth_version = int(auth_version) if auth_version is not None else None
        self.session = requests.Session()
        self.session.mount("http://", _TransferAdapter(pool_maxsize=100))
        self.session.mount("https://", _TransferAdapter(pool_maxsize=100))
        self.refresh_lock = refresh_lock or threading.Lock()
        self.upload_context = threading.local()
        self.destination_locks_lock = threading.Lock()
        self.destination_locks = {}
        self.rate_key = _account_key(self.client_id, self.refresh_token, self.drive_id)

    def _destination_lock(self, path):
        with self.destination_locks_lock:
            return self.destination_locks.setdefault(path, threading.Lock())

    def _wait_rate(self, kind):
        # Account-wide API limits; signed part PUTs do not use this limiter.
        interval = {"list": 1 / 3.9, "link": 1 / 0.9, "other": 1 / 14.9}[kind]
        with _GLOBAL_RATE_LOCK:
            state = _GLOBAL_RATE_STATES.setdefault(
                self.rate_key + ":" + kind, {"last": 0.0, "lock": threading.Lock()}
            )
        with state["lock"]:
            delay = interval - (time.monotonic() - state["last"])
            if delay > 0:
                time.sleep(delay)
            state["last"] = time.monotonic()

    def _persist(self):
        expected_tokens = {
            key: self.config.get(key)
            for key in ("access_token", "refresh_token", "refresh_proof", "expires_at", "drive_id")
        }
        self.config.update(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "refresh_proof": self.refresh_proof,
                "expires_at": self.expires_at,
                "drive_id": self.drive_id,
            }
        )
        if self.save_config:
            try:
                result = self.save_config(
                    dict(self.config), expected_tokens=expected_tokens
                )
            except TypeError:
                # Keep compatibility with callers that implement the original
                # one-argument callback contract.
                result = self.save_config(dict(self.config))
            if isinstance(result, dict) and result.get("conflict"):
                self._adopt_config(result.get("config") or {})

    def _adopt_config(self, config):
        if not isinstance(config, dict):
            return
        if config.get("access_token"):
            self.access_token = str(config["access_token"])
        if config.get("refresh_token"):
            self.refresh_token = str(config["refresh_token"])
        if config.get("refresh_proof"):
            self.refresh_proof = str(config["refresh_proof"])
        if config.get("expires_at") is not None:
            try:
                self.expires_at = float(config["expires_at"])
            except (TypeError, ValueError):
                pass
        if config.get("drive_id"):
            self.drive_id = str(config["drive_id"])
        self.config.update(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "refresh_proof": self.refresh_proof,
                "expires_at": self.expires_at,
                "drive_id": self.drive_id,
            }
        )
        self.rate_key = _account_key(self.client_id, self.refresh_token, self.drive_id)

    def _adopt_persisted_config(self):
        if not self.load_config:
            return False
        try:
            row = self.load_config()
        except Exception:
            return False
        if not isinstance(row, dict):
            return False
        if self.auth_version is not None and int(row.get("authVersion", -1)) != self.auth_version:
            return False
        config = row.get("config")
        if not isinstance(config, dict):
            return False
        try:
            expires_at = float(config.get("expires_at") or 0)
        except (TypeError, ValueError):
            expires_at = 0
        if config.get("access_token") and expires_at > time.time() + 90:
            self._adopt_config(config)
            return True
        return False

    def _refresh_access_token(self, force=False, invalid_token=None):
        if not force and self.access_token and self.expires_at > time.time() + 90:
            return
        with self.refresh_lock:
            self._adopt_persisted_config()
            if force and invalid_token is not None and self.access_token != invalid_token:
                return
            if not force and self.access_token and self.expires_at > time.time() + 90:
                return
            if self.auth_mode == "service":
                response = self.session.post(
                    self.auth_service_url + "/v1/aliyun/token/refresh",
                    json={
                        "refresh_token": self.refresh_token,
                        "refresh_proof": self.refresh_proof,
                    },
                    timeout=(30, 60),
                )
            else:
                response = self.session.post(
                    self.oauth_url,
                    json={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type": "refresh_token",
                        "refresh_token": self.refresh_token,
                    },
                    timeout=(30, 60),
                )
            data = _response_json(response)
            if response.status_code >= 400 or not data.get("access_token"):
                raise RuntimeError(_api_error("Aliyun OAuth failed", response, data))
            self.access_token = data["access_token"]
            if data.get("refresh_token"):
                self.refresh_token = data["refresh_token"]
            if data.get("refresh_proof"):
                self.refresh_proof = data["refresh_proof"]
            self.expires_at = time.time() + int(data.get("expires_in") or 7200)
            self.rate_key = _account_key(self.client_id, self.refresh_token, self.drive_id)
            self._persist()

    def _request(self, endpoint, data=None, method="POST", auth_retry=True, attempt=0):
        kind = "list" if endpoint.endswith("/list") else (
            "link" if "getDownloadUrl" in endpoint else "other"
        )
        self._wait_rate(kind)
        self._refresh_access_token()
        request_token = self.access_token
        request_data = data(request_token) if callable(data) else data
        try:
            response = self.session.request(
                method,
                self.api_url + endpoint,
                json=request_data,
                headers={"Authorization": "Bearer " + request_token},
                timeout=(30, 120),
            )
        except requests.RequestException as exc:
            if attempt < 3:
                time.sleep(2 ** attempt)
                return self._request(endpoint, data, method, auth_retry, attempt + 1)
            raise RuntimeError("Aliyun API request failed after retries") from exc
        result = _response_json(response)
        code = str(result.get("code") or "")
        token_invalid = response.status_code == 401 or code in {
            "AccessTokenInvalid",
            "AccessTokenExpired",
            "I400JD",
        }
        if token_invalid and auth_retry:
            self._refresh_access_token(force=True, invalid_token=request_token)
            return self._request(endpoint, data, method, auth_retry=False, attempt=attempt)
        if response.status_code == 429 or 500 <= response.status_code < 600:
            if attempt < 3:
                retry_after = 0
                try:
                    retry_after = float(response.headers.get("Retry-After", 0))
                except (AttributeError, TypeError, ValueError):
                    pass
                time.sleep(max(retry_after, 2 ** attempt))
                return self._request(endpoint, data, method, auth_retry, attempt + 1)
        if response.status_code >= 400 or code:
            raise AliyunAPIError(_api_error("Aliyun API request failed", response, result), code)
        return result

    def _ensure_drive(self):
        if self.drive_id:
            return
        data = self._request("/adrive/v1.0/user/getDriveInfo", {})
        candidates = [self.drive_type, "default", "resource", "backup"]
        candidates = list(dict.fromkeys(candidates))
        self.drive_id = next(
            (
                str(data.get(candidate + "_drive_id"))
                for candidate in candidates
                if data.get(candidate + "_drive_id")
            ),
            "",
        )
        if not self.drive_id:
            raise RuntimeError("Aliyun did not return any supported drive ID")
        self.rate_key = _account_key(self.client_id, self.refresh_token, self.drive_id)
        self._persist()

    def _list_id(self, parent_id):
        self._ensure_drive()
        marker = ""
        files = []
        while True:
            data = self._request(
                "/adrive/v1.0/openFile/list",
                {
                    "drive_id": self.drive_id,
                    "parent_file_id": parent_id,
                    "limit": 200,
                    "marker": marker,
                    "order_by": "name",
                    "order_direction": "ASC",
                },
            )
            files.extend(data.get("items") or [])
            marker = data.get("next_marker") or ""
            if not marker:
                return files

    def _resolve(self, path, allow_root=True, forbidden_id=None):
        path = normalize_path(path, allow_root=allow_root)
        current = {
            "file_id": self.root_folder_id,
            "type": "folder",
            "name": "root",
            "size": 0,
        }
        if forbidden_id and current["file_id"] == forbidden_id:
            raise ValueError("a directory cannot be moved into itself")
        for part in path.strip("/").split("/") if path != "/" else []:
            if current.get("type") != "folder":
                raise NotADirectoryError(path)
            matches = [item for item in self._list_id(current["file_id"]) if item.get("name") == part]
            if not matches:
                raise FileNotFoundError(path)
            # Preserve the newest item if an older API operation left duplicate
            # names in the same directory.
            current = sorted(matches, key=lambda item: item.get("updated_at") or "")[-1]
            if forbidden_id and current["file_id"] == forbidden_id:
                raise ValueError("a directory cannot be moved into itself")
        return current

    def list(self, path, details=False):
        parent = self._resolve(path)
        if parent.get("type") != "folder":
            raise NotADirectoryError(path)
        result = [self._entry(item, details) for item in self._list_id(parent["file_id"])]
        result.sort(key=lambda x: (not x["is_dir"], x["name"].casefold()))
        return result

    @staticmethod
    def _entry(item, details):
        is_dir = item.get("type") == "folder"
        entry = {
            "name": item.get("name") or item.get("file_name"),
            "is_dir": is_dir,
            "size": None if is_dir else int(item.get("size") or 0),
        }
        if details:
            entry["created_at"] = item.get("local_created_at") or item.get("created_at")
            entry["modified_at"] = item.get("local_modified_at") or item.get("updated_at")
            if str(item.get("content_hash_name") or "sha1").lower() == "sha1":
                entry["sha1"] = _sha1(item.get("content_hash"))
            entry["fingerprint"] = fileFingerprint(
                "aliyun", item.get("file_id"), item.get("updated_at"),
                item.get("content_hash") or item.get("crc64_hash"),
            )
        return entry

    def file_metadata(self, path):
        # Match download/read_range's duplicate-name resolution exactly.
        item = self._resolve(path, allow_root=False)
        if item.get("type") == "folder":
            raise IsADirectoryError(path)
        return self._entry(item, True)

    def mkdir(self, path):
        path = normalize_path(path)
        self._ensure_drive()
        current_id = self.root_folder_id
        for part in path.strip("/").split("/") if path != "/" else []:
            matches = [item for item in self._list_id(current_id) if item.get("name") == part]
            if matches:
                folder = matches[-1]
                if folder.get("type") != "folder":
                    raise FileExistsError(path)
                current_id = folder["file_id"]
                continue
            created = self._request(
                "/adrive/v1.0/openFile/create",
                {
                    "drive_id": self.drive_id,
                    "parent_file_id": current_id,
                    "name": part,
                    "type": "folder",
                    "check_name_mode": "refuse",
                },
            )
            current_id = created["file_id"]

    def _delete_id(self, file_id):
        endpoint = "/adrive/v1.0/openFile/recyclebin/trash"
        if self.remove_way == "delete":
            endpoint = "/adrive/v1.0/openFile/delete"
        self._request(endpoint, {"drive_id": self.drive_id, "file_id": file_id})

    def delete(self, path):
        item = self._resolve(path, allow_root=False)
        self._delete_id(item["file_id"])

    def download(self, path, target, progress=None, cancel=None):
        item = self._resolve(path, allow_root=False)
        if item.get("type") == "folder":
            raise IsADirectoryError(path)
        data = self._request(
            "/adrive/v1.0/openFile/getDownloadUrl",
            {"drive_id": self.drive_id, "file_id": item["file_id"], "expire_sec": 14400},
        )
        url = data.get("url")
        if not url:
            raise RuntimeError("Aliyun did not return a download URL")
        response = self.session.get(url, stream=True, timeout=(30, 300))
        response.raise_for_status()
        size = int(item.get("size") or response.headers.get("Content-Length") or 0)
        done = 0
        try:
            for chunk in response.iter_content(1024 * 1024):
                check_cancel(cancel)
                if not chunk:
                    continue
                target.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done / size if size else 0.0)
        finally:
            response.close()
        if size and done != size:
            raise IOError("Aliyun download ended before the expected file size")
        if progress:
            progress(1.0)

    def read_range(self, path, offset, length, cancel=None):
        check_cancel(cancel)
        item = self._resolve(path, allow_root=False)
        if item.get("type") == "folder":
            raise IsADirectoryError(path)
        data = self._request("/adrive/v1.0/openFile/getDownloadUrl", {
            "drive_id": self.drive_id, "file_id": item["file_id"], "expire_sec": 14400,
        })
        if not data.get("url"):
            raise RuntimeError("Aliyun did not return a download URL")
        end = offset + length - 1
        response = self.session.get(data["url"], headers={"Range": "bytes={}-{}".format(offset, end)},
                                    stream=True, timeout=(30, 300))
        try:
            response.raise_for_status()
            expected = "bytes {}-{}/".format(offset, end)
            if response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(expected):
                raise IOError("Aliyun did not honor the requested byte range")
            result = bytearray()
            for chunk in response.iter_content(length):
                check_cancel(cancel)
                result.extend(chunk)
                if len(result) > length:
                    raise IOError("Aliyun returned an invalid byte range")
            if len(result) != length:
                raise IOError("Aliyun range download ended before the expected size")
            return bytes(result)
        finally:
            response.close()

    def upload(self, path, source, size=None, progress=None, cancel=None):
        path = normalize_path(path, allow_root=False)
        with self._destination_lock(path):
            try:
                return self._upload_impl(path, source, size, progress, cancel)
            except Exception:
                context = self.upload_context
                if getattr(context, "file_id", None) and not getattr(context, "completed", False):
                    self._abort_upload(context.file_id)
                raise
            finally:
                cached_source = getattr(self.upload_context, "cached_source", None)
                if cached_source is not None:
                    cached_source.close()
                self.upload_context.cached_source = None
                self.upload_context.file_id = None
                self.upload_context.upload_id = None
                self.upload_context.completed = False

    def _abort_upload(self, file_id):
        try:
            # Incomplete uploads are not useful and should not accumulate in
            # the drive or consume quota. Use permanent delete for the upload
            # session itself, independent of the user's normal remove policy.
            self._request("/adrive/v1.0/openFile/delete", {
                "drive_id": self.drive_id,
                "file_id": file_id,
            })
        except Exception:
            pass

    @staticmethod
    def _read_exact(source, length, cancel):
        chunks = []
        while length:
            check_cancel(cancel)
            chunk = source.read(min(1024 * 1024, length))
            if not chunk:
                raise IOError("source stream ended before the expected file size")
            chunks.append(chunk)
            length -= len(chunk)
        return b"".join(chunks)

    def _create_upload(self, data, source, size, cancel):
        endpoint = "/adrive/v1.0/openFile/create"
        check_cancel(cancel)
        metadata = getattr(source, "metadata", {})
        content_hash = _sha1(metadata.get("sha1"))
        range_read = None
        if getattr(source, "can_read_range", False) is True:
            range_read = source.read_range
        elif callable(getattr(source, "seekable", None)) and source.seekable():
            origin = source.tell()

            def range_read(offset, length):
                position = source.tell()
                try:
                    source.seek(origin + offset)
                    return self._read_exact(source, length, cancel)
                finally:
                    source.seek(position)

        if self.rapid_upload and content_hash and size > 0 and range_read is not None:
            created = self._request(endpoint, self._proof_data(data, content_hash, range_read, size, cancel))
            return created, source, bool(created.get("rapid_upload"))
        if not self.rapid_upload or size <= 100 * 1024:
            return self._request(endpoint, data), source, False

        prefix = self._read_exact(source, 1024, cancel)
        source = _PrefixReader(prefix, source)
        try:
            created = self._request(endpoint, {
                **data, "pre_hash": hashlib.sha1(prefix).hexdigest().upper(),
            })
            return created, source, False
        except AliyunAPIError as exc:
            if exc.code != "PreHashMatched":
                raise

        # Only pre-hash matches need a complete local cache. It allows both
        # token-dependent proof reads and normal-upload fallback from SMB pipes.
        cached = tempfile.TemporaryFile(mode="w+b")
        self.upload_context.cached_source = cached
        digest = None if content_hash else hashlib.sha1()
        remaining = size
        while remaining:
            chunk = self._read_exact(source, min(1024 * 1024, remaining), cancel)
            cached.write(chunk)
            if digest is not None:
                digest.update(chunk)
            remaining -= len(chunk)
        content_hash = content_hash or digest.hexdigest().upper()
        metadata["sha1"] = content_hash

        def cached_range(offset, length):
            cached.seek(offset)
            proof = self._read_exact(cached, length, cancel)
            cached.seek(0)
            return proof

        created = self._request(endpoint, self._proof_data(data, content_hash, cached_range, size, cancel))
        cached.seek(0)
        return created, cached, True

    def _proof_data(self, data, content_hash, read_range, size, cancel):
        def proof_data(token):
            check_cancel(cancel)
            offset = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:16], 16) % size
            length = min(8, size - offset)
            proof = read_range(offset, length)
            check_cancel(cancel)
            if len(proof) != length:
                raise IOError("source stream ended before the expected file size")
            return {
                **data,
                "content_hash": content_hash,
                "content_hash_name": "sha1",
                "proof_version": "v1",
                "proof_code": base64.b64encode(proof).decode("ascii"),
            }
        return proof_data

    def _upload_impl(self, path, source, size=None, progress=None, cancel=None):
        self.upload_context.file_id = None
        self.upload_context.upload_id = None
        self.upload_context.completed = False
        self.upload_context.cached_source = None
        path = normalize_path(path, allow_root=False)
        parent_path, name = posixpath.split(path)
        parent = self._resolve(parent_path or "/")
        self._ensure_drive()
        self._assert_file_destination(parent["file_id"], name, path)
        if size is None:
            current = source.tell()
            source.seek(0, 2)
            size = source.tell() - current
            source.seek(current)
        size = int(size)
        if size < 0:
            raise ValueError("file size must not be negative")
        part_size = max(self.PART_SIZE, math.ceil(size / self.MAX_PARTS) if size else self.PART_SIZE)
        part_count = max(1, math.ceil(size / part_size) if size else 1)
        part_info = [{"part_number": index + 1} for index in range(part_count)]
        created, source, _source_consumed = self._create_upload(
            {
                "drive_id": self.drive_id,
                "parent_file_id": parent["file_id"],
                "name": name,
                "type": "file",
                "size": size,
                "check_name_mode": "ignore",
                "part_info_list": part_info,
                **_upload_times(getattr(source, "metadata", {})),
            }, source, size, cancel,
        )
        file_id = created["file_id"]
        upload_id = created.get("upload_id")
        self.upload_context.file_id = file_id
        if created.get("rapid_upload"):
            # The create response already committed the file; there is no
            # multipart upload session to complete or abort.
            self.upload_context.completed = True
            self._remove_duplicates(parent["file_id"], name, file_id)
            if progress:
                progress(1.0)
            return
        self.upload_context.upload_id = upload_id
        uploaded_parts = created.get("part_info_list") or []
        if not created.get("rapid_upload"):
            if not upload_id:
                raise RuntimeError("Aliyun did not return an upload ID")
            if len(uploaded_parts) != part_count or any(
                not item.get("upload_url") for item in uploaded_parts
            ):
                uploaded_parts = self._get_upload_parts(file_id, upload_id, part_count)
            upload_urls_at = time.monotonic()
            total_done = 0

            def on_read(count):
                nonlocal total_done
                total_done += count
                if progress:
                    progress(total_done / size if size else 1.0)

            # Read the current list by index. The list is replaced whenever
            # upload URLs are refreshed, so iterating a stale list would keep
            # using expired URLs for all following parts.
            for index in range(part_count):
                part = uploaded_parts[index]
                check_cancel(cancel)
                length = min(part_size, max(0, size - index * part_size))
                if time.monotonic() - upload_urls_at > 45 * 60:
                    uploaded_parts = self._get_upload_parts(file_id, upload_id, part_count)
                    upload_urls_at = time.monotonic()
                    part = uploaded_parts[index]
                reader = _PartReader(source, length, cancel, on_read)
                try:
                    for retry_index in range(3):
                        check_cancel(cancel)
                        if retry_index and not part.get("upload_url"):
                            uploaded_parts = self._get_upload_parts(file_id, upload_id, part_count)
                            upload_urls_at = time.monotonic()
                            part = uploaded_parts[index]
                        reader.reset()
                        try:
                            response = self.session.put(
                                part["upload_url"],
                                data=reader,
                                headers={"Content-Length": str(length)},
                                timeout=(30, 300),
                            )
                        except requests.RequestException as exc:
                            if retry_index == 2:
                                raise RuntimeError(
                                    "Aliyun part upload failed after retries: part {}/{}, {}".format(
                                        index + 1, part_count, type(exc).__name__
                                    )
                                ) from exc
                            time.sleep(2 ** retry_index)
                            continue
                        try:
                            status = response.status_code
                            detail = _part_error(response) if status not in (200, 201, 204, 409) else ""
                            try:
                                retry_after = float(response.headers.get("Retry-After", 0))
                            except (AttributeError, TypeError, ValueError):
                                retry_after = 0
                        finally:
                            response.close()
                        if status in (200, 201, 204, 409):
                            if reader.position != length and status != 409:
                                raise IOError("Aliyun part upload did not consume the expected file size")
                            break
                        if status in (401, 403, 404):
                            uploaded_parts = self._get_upload_parts(file_id, upload_id, part_count)
                            upload_urls_at = time.monotonic()
                            part = uploaded_parts[index]
                            if retry_index == 2:
                                raise RuntimeError("Aliyun upload URL expired after retries: part {}/{}, {}".format(
                                    index + 1, part_count, detail
                                ))
                            time.sleep(2 ** retry_index)
                            continue
                        if status != 429 and not 500 <= status < 600:
                            raise RuntimeError("Aliyun part upload failed: part {}/{}, {}".format(
                                index + 1, part_count, detail
                            ))
                        if retry_index == 2:
                            raise RuntimeError("Aliyun part upload failed after retries: part {}/{}, {}".format(
                                index + 1, part_count, detail
                            ))
                        time.sleep(max(retry_after, 2 ** retry_index))
                    # A 409 may acknowledge an earlier successful attempt.
                    while reader.position < length:
                        reader.read(min(1024 * 1024, length - reader.position))
                finally:
                    reader.close()
            if total_done != size:
                raise IOError("source stream ended before the expected file size")
        check_cancel(cancel)
        completed = self._request(
            "/adrive/v1.0/openFile/complete",
            {"drive_id": self.drive_id, "file_id": file_id, "upload_id": upload_id},
        )
        self.upload_context.completed = True
        final_id = completed.get("file_id") or file_id
        try:
            check_cancel(cancel)
        except TransferCancelled:
            self._abort_upload(final_id)
            raise
        self._remove_duplicates(parent["file_id"], name, final_id)
        if progress:
            progress(1.0)

    def _assert_file_destination(self, parent_id, name, path):
        for item in self._list_id(parent_id):
            if item.get("name") == name and item.get("type") == "folder":
                raise IsADirectoryError(path)

    def _remove_duplicates(self, parent_id, name, keep_id):
        matches = [item for item in self._list_id(parent_id) if item.get("name") == name]
        if any(item.get("type") == "folder" for item in matches):
            # A directory may have appeared after the preflight check. Roll
            # back the new file and never delete or rename that directory.
            self._abort_upload(keep_id)
            raise IsADirectoryError(name)
        for item in matches:
            if item.get("type") == "file" and item.get("file_id") != keep_id:
                self._delete_id(item["file_id"])

    def _get_upload_parts(self, file_id, upload_id, part_count):
        data = self._request(
            "/adrive/v1.0/openFile/getUploadUrl",
            {
                "drive_id": self.drive_id,
                "file_id": file_id,
                "upload_id": upload_id,
                "part_info_list": [{"part_number": index + 1} for index in range(part_count)],
            },
        )
        parts = data.get("part_info_list") or []
        if len(parts) != part_count:
            raise RuntimeError("Aliyun returned an incomplete part URL list")
        return parts

    def copy(self, source_path, destination_path, size=None, progress=None, cancel=None, metadata=None):
        source_path = normalize_path(source_path, allow_root=False)
        destination_path = normalize_path(destination_path, allow_root=False)
        if source_path == destination_path:
            if progress:
                progress(1.0)
            return
        with self._destination_lock(destination_path):
            source = self._resolve(source_path, allow_root=False)
            if source.get("type") == "folder":
                raise IsADirectoryError(source_path)
            parent_path, name = posixpath.split(destination_path)
            destination_parent = self._resolve(parent_path or "/")
            self._assert_file_destination(destination_parent["file_id"], name, destination_path)
            check_cancel(cancel)
            copied = self._request(
                "/adrive/v1.0/openFile/copy",
                {
                    "drive_id": self.drive_id,
                    "file_id": source["file_id"],
                    "to_parent_file_id": destination_parent["file_id"],
                    "auto_rename": False,
                },
            )
            keep_id = copied.get("file_id")
            if not keep_id:
                raise RuntimeError("Aliyun did not return the copied file ID")
            try:
                check_cancel(cancel)
            except TransferCancelled:
                self._abort_upload(keep_id)
                raise
            self._remove_duplicates(destination_parent["file_id"], name, keep_id)
            if progress:
                progress(1.0)

    def can_move_to(self, destination):
        if not isinstance(destination, AliyunDriveDriver) or self.api_url != destination.api_url:
            return False
        self._ensure_drive()
        destination._ensure_drive()
        return self.drive_id == destination.drive_id

    def move(self, source_path, destination_path, size=None, progress=None, cancel=None):
        return self.move_to(source_path, self, destination_path, progress, cancel)

    def move_to(self, source_path, destination, destination_path, progress=None, cancel=None):
        if not self.can_move_to(destination):
            raise ValueError("cloud moves require the same Aliyun drive")
        source_path = normalize_path(source_path, allow_root=False)
        destination_path = normalize_path(destination_path, allow_root=False)
        parent_path, name = posixpath.split(destination_path)
        child_path(parent_path, name)
        with destination._destination_lock(destination_path):
            check_cancel(cancel)
            source = self._resolve(source_path, allow_root=False)
            parent = destination._resolve(parent_path or "/", forbidden_id=source["file_id"])
            if parent.get("type") != "folder":
                raise NotADirectoryError(parent_path)
            matches = [item for item in destination._list_id(parent["file_id"]) if item.get("name") == name]
            if any(item.get("file_id") != source["file_id"] for item in matches):
                raise FileExistsError(destination_path)
            if any(item.get("file_id") == source["file_id"] for item in matches):
                if progress:
                    progress(1.0)
                return
            check_cancel(cancel)
            if (source.get("parent_file_id") == parent["file_id"]
                    or (self is destination and posixpath.dirname(source_path) == parent_path)):
                self._request("/adrive/v1.0/openFile/update", {
                    "drive_id": self.drive_id, "file_id": source["file_id"],
                    "name": name, "check_name_mode": "refuse",
                })
            else:
                self._request("/adrive/v1.0/openFile/move", {
                    "drive_id": self.drive_id, "file_id": source["file_id"],
                    "to_parent_file_id": parent["file_id"], "new_name": name,
                    "check_name_mode": "refuse",
                })
            # The cloud has committed the operation. A late cancellation must
            # not delete the moved object or report it as cancelled.
            if progress:
                progress(1.0)

    def rename(self, path, name, cancel=None):
        path = normalize_path(path, allow_root=False)
        destination = child_path(posixpath.dirname(path), name)
        return self.move(path, destination, cancel=cancel)


def _response_json(response):
    try:
        data = response.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _part_error(response):
    detail = "HTTP {}".format(response.status_code)
    try:
        code = ET.fromstring(response.text[:8192]).findtext("Code") or ""
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", code):
            detail += " " + code
    except (ET.ParseError, TypeError):
        pass
    return detail


def _api_error(prefix, response, data):
    detail = data.get("message") or data.get("code") or response.text[:300]
    return "{}: HTTP {} {}".format(prefix, response.status_code, detail).strip()
