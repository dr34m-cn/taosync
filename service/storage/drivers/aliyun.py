import base64
import binascii
import hashlib
import json
import math
import posixpath
import tempfile
import threading
import time

import requests

from common.fileFingerprint import fileFingerprint

from .base import StorageDriver, TransferCancelled, check_cancel, normalize_path


_GLOBAL_RATE_LOCK = threading.Lock()
_GLOBAL_RATE_STATES = {}


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
        self.remaining = length
        self.length = length
        self.cancel = cancel
        self.on_read = on_read

    def __len__(self):
        return self.length

    def read(self, size=-1):
        check_cancel(self.cancel)
        if self.remaining <= 0:
            return b""
        if size is None or size < 0:
            size = self.remaining
        data = self.source.read(min(size, self.remaining))
        self.remaining -= len(data)
        if data:
            self.on_read(len(data))
        return data


class AliyunDriveDriver(StorageDriver):
    """Aliyun Drive Open API driver.

    It uses the public OAuth/OpenFile endpoints rather than private web-client
    APIs. A developer application client ID, client secret and refresh token
    are therefore required.
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
        self.client_id = str(self.config.get("client_id") or "").strip()
        self.client_secret = str(self.config.get("client_secret") or "").strip()
        self.refresh_token = str(self.config.get("refresh_token") or "").strip()
        if not self.client_id or not self.client_secret or not self.refresh_token:
            raise ValueError("Aliyun client_id, client_secret and refresh_token are required")
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
        self.save_config = save_config
        self.load_config = load_config
        self.auth_version = int(auth_version) if auth_version is not None else None
        self.session = requests.Session()
        self.refresh_lock = refresh_lock or threading.Lock()
        self.upload_context = threading.local()
        self.destination_locks_lock = threading.Lock()
        self.destination_locks = {}
        self.rate_key = _account_key(self.client_id, self.refresh_token, self.drive_id)

    def _destination_lock(self, path):
        with self.destination_locks_lock:
            return self.destination_locks.setdefault(path, threading.Lock())

    def _wait_rate(self, kind):
        # Conservative per-driver limits based on the limits used by AList's
        # official Open driver. They also protect a single account when jobs
        # submit up to twenty concurrent copy workers.
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
            for key in ("access_token", "refresh_token", "expires_at", "drive_id")
        }
        self.config.update(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
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
        try:
            response = self.session.request(
                method,
                self.api_url + endpoint,
                json=data,
                headers={"Authorization": "Bearer " + self.access_token},
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
            raise RuntimeError(_api_error("Aliyun API request failed", response, result))
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

    def _resolve(self, path, allow_root=True):
        path = normalize_path(path, allow_root=allow_root)
        current = {
            "file_id": self.root_folder_id,
            "type": "folder",
            "name": "root",
            "size": 0,
        }
        for part in path.strip("/").split("/") if path != "/" else []:
            matches = [item for item in self._list_id(current["file_id"]) if item.get("name") == part]
            if not matches:
                raise FileNotFoundError(path)
            # Preserve the newest item if an older API operation left duplicate
            # names in the same directory.
            current = sorted(matches, key=lambda item: item.get("updated_at") or "")[-1]
        return current

    def list(self, path, details=False):
        parent = self._resolve(path)
        if parent.get("type") != "folder":
            raise NotADirectoryError(path)
        result = []
        for item in self._list_id(parent["file_id"]):
            is_dir = item.get("type") == "folder"
            entry = {
                "name": item.get("name") or item.get("file_name"),
                "is_dir": is_dir,
                "size": None if is_dir else int(item.get("size") or 0),
            }
            if details:
                entry["fingerprint"] = fileFingerprint(
                        "aliyun",
                        item.get("file_id"),
                        item.get("updated_at"),
                        item.get("content_hash") or item.get("crc64_hash"),
                    )
            result.append(entry)
        result.sort(key=lambda x: (not x["is_dir"], x["name"].casefold()))
        return result

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

    def _upload_impl(self, path, source, size=None, progress=None, cancel=None):
        self.upload_context.file_id = None
        self.upload_context.upload_id = None
        self.upload_context.completed = False
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
        part_size = max(self.PART_SIZE, math.ceil(size / self.MAX_PARTS) if size else self.PART_SIZE)
        part_count = max(1, math.ceil(size / part_size) if size else 1)
        part_info = [{"part_number": index + 1} for index in range(part_count)]
        created = self._request(
            "/adrive/v1.0/openFile/create",
            {
                "drive_id": self.drive_id,
                "parent_file_id": parent["file_id"],
                "name": name,
                "type": "file",
                "size": size,
                "check_name_mode": "ignore",
                "part_info_list": part_info,
            },
        )
        file_id = created["file_id"]
        upload_id = created.get("upload_id")
        self.upload_context.file_id = file_id
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
                with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as part_buffer:
                    remaining = length
                    while remaining:
                        check_cancel(cancel)
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise IOError("source stream ended before the expected file size")
                        part_buffer.write(chunk)
                        remaining -= len(chunk)
                        on_read(len(chunk))
                    for retry_index in range(3):
                        check_cancel(cancel)
                        if retry_index and not part.get("upload_url"):
                            uploaded_parts = self._get_upload_parts(file_id, upload_id, part_count)
                            upload_urls_at = time.monotonic()
                            part = uploaded_parts[index]
                        part_buffer.seek(0)
                        reader = _PartReader(part_buffer, length, cancel, lambda count: None)
                        try:
                            response = self.session.put(
                                part["upload_url"],
                                data=reader,
                                headers={"Content-Length": str(length)},
                                timeout=(30, 300),
                            )
                        except requests.RequestException as exc:
                            if retry_index == 2:
                                raise RuntimeError("Aliyun part upload failed after retries") from exc
                            time.sleep(2 ** retry_index)
                            continue
                        if response.status_code in (200, 201, 204, 409):
                            break
                        if response.status_code in (401, 403, 404):
                            uploaded_parts = self._get_upload_parts(file_id, upload_id, part_count)
                            upload_urls_at = time.monotonic()
                            part = uploaded_parts[index]
                            if retry_index == 2:
                                raise RuntimeError("Aliyun upload URL expired after retries")
                            continue
                        if response.status_code not in (429,) and not 500 <= response.status_code < 600:
                            raise RuntimeError("Aliyun part upload failed: HTTP {}".format(response.status_code))
                        if retry_index == 2:
                            raise RuntimeError("Aliyun part upload failed after retries")
                        try:
                            retry_after = float(response.headers.get("Retry-After", 0))
                        except (AttributeError, TypeError, ValueError):
                            retry_after = 0
                        time.sleep(max(retry_after, 2 ** retry_index))
            if total_done != size:
                raise IOError("source stream ended before the expected file size")
        else:
            # A rapid-upload response still consumes the source stream when
            # TaoSync is piping a different backend, otherwise the producer can
            # block on a full pipe and report a false transfer failure.
            consumed = 0
            while consumed < size:
                check_cancel(cancel)
                chunk = source.read(min(1024 * 1024, size - consumed))
                if not chunk:
                    raise IOError("source stream ended before the expected file size")
                consumed += len(chunk)
                if progress:
                    progress(consumed / size if size else 1.0)
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

    def copy(self, source_path, destination_path, size=None, progress=None, cancel=None):
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


def _response_json(response):
    try:
        data = response.json()
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _api_error(prefix, response, data):
    detail = data.get("message") or data.get("code") or response.text[:300]
    return "{}: HTTP {} {}".format(prefix, response.status_code, detail).strip()
