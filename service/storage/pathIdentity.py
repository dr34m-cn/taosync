import base64
import binascii
import hashlib
import json
import ntpath
import os
import posixpath
from urllib.parse import urlsplit

from service.storage.drivers.base import normalize_path


def virtual_paths_overlap(first_path, second_path, case_sensitive=True):
    first = normalize_path(first_path)
    second = normalize_path(second_path)
    if not case_sensitive:
        first = first.casefold()
        second = second.casefold()
    return _path_overlaps(first, second)


def _mount_lookup(mounts):
    rows = mounts.values() if isinstance(mounts, dict) else mounts
    return {str(row["name"]): row for row in rows}


def _resolve_mount(mounts, path):
    normalized = normalize_path(path, allow_root=False)
    parts = normalized.strip("/").split("/")
    mount = mounts.get(parts[0])
    if mount is None:
        return None, None
    relative = "/" + "/".join(parts[1:]) if len(parts) > 1 else "/"
    return mount, relative


def _path_overlaps(first, second, separator="/"):
    first = first.rstrip(separator) or separator
    second = second.rstrip(separator) or separator
    return (
        first == second
        or first.startswith(second.rstrip(separator) + separator)
        or second.startswith(first.rstrip(separator) + separator)
    )


def _local_path(config, relative):
    root = config.get("root_path") or config.get("path")
    if not root:
        return None
    root = os.path.realpath(os.path.abspath(os.path.expanduser(str(root))))
    parts = normalize_path(relative).strip("/").split("/") if relative != "/" else []
    return os.path.normcase(os.path.realpath(os.path.join(root, *parts)))


def _local_paths_overlap(first_config, first_relative, second_config, second_relative):
    first = _local_path(first_config, first_relative)
    second = _local_path(second_config, second_relative)
    if first is None or second is None:
        return False
    try:
        common = os.path.commonpath((first, second))
    except ValueError:
        return False
    return common == first or common == second


def _host(value):
    return str(value or "").strip().rstrip(".").casefold()


def _smb_descriptor(config, relative):
    server = _host(config.get("host") or config.get("server"))
    share = str(config.get("share") or "").strip().strip("\\/").casefold()
    try:
        port = int(config.get("port") or 445)
    except (TypeError, ValueError):
        return None
    if not server or not share:
        return None
    root = str(config.get("root_path") or "").replace("/", "\\").strip("\\")
    child = normalize_path(relative).strip("/").replace("/", "\\")
    path = ntpath.normpath(ntpath.join("\\", root, child)).casefold()
    return ("smb", server, port, share), path


def _remote_descriptor(driver_type, config, relative):
    default_port = 21 if driver_type == "ftp" else 22
    try:
        port = int(config.get("port") or default_port)
    except (TypeError, ValueError):
        return None
    host = _host(config.get("host"))
    username_default = "anonymous" if driver_type == "ftp" else ""
    username = str(config.get("username") or username_default).strip()
    if not host or not username:
        return None
    root = str(config.get("root_path") or "/").replace("\\", "/")
    root = "/" + root.strip("/") if root.strip("/") else "/"
    path = posixpath.normpath(posixpath.join(root, normalize_path(relative).lstrip("/")))
    return (driver_type, host, port, username), path


def _api_identity(value):
    value = str(value or "https://openapi.alipan.com").strip().rstrip("/")
    parsed = urlsplit(value)
    if not parsed.netloc:
        return value.casefold()
    scheme = (parsed.scheme or "https").casefold()
    host = (parsed.hostname or "").casefold()
    try:
        port = parsed.port
    except ValueError:
        return value.casefold()
    if port in (80 if scheme == "http" else 443,):
        port = None
    authority = host if port is None else "{}:{}".format(host, port)
    path = posixpath.normpath(parsed.path or "/").rstrip("/")
    return "{}://{}{}".format(scheme, authority, "" if path == "/" else path)


def _jwt_subject(token):
    try:
        payload = str(token).split(".")[1]
        payload += "=" * (-len(payload) % 4)
        value = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        subject = value.get("sub")
        return str(subject) if subject is not None else None
    except (IndexError, ValueError, TypeError, KeyError, json.JSONDecodeError,
            binascii.Error, UnicodeDecodeError):
        return None


def _aliyun_account(config):
    client_id = str(config.get("client_id") or "").strip()
    refresh_token = str(config.get("refresh_token") or "").strip()
    subject = _jwt_subject(refresh_token)
    if client_id and subject:
        return "subject", client_id, subject
    if client_id and refresh_token:
        digest = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
        return "token", client_id, digest
    return None


def _aliyun_same_backend(first, second):
    if _api_identity(first.get("api_url")) != _api_identity(second.get("api_url")):
        return False
    first_drive = str(first.get("drive_id") or "").strip()
    second_drive = str(second.get("drive_id") or "").strip()
    if first_drive and second_drive:
        return first_drive == second_drive
    first_account = _aliyun_account(first)
    second_account = _aliyun_account(second)
    if first_account is None or first_account != second_account:
        return False
    return str(first.get("drive_type") or "resource") == str(
        second.get("drive_type") or "resource"
    )


def _aliyun_paths_overlap(first_config, first_relative, second_config, second_relative):
    if not _aliyun_same_backend(first_config, second_config):
        return False
    first_root = str(first_config.get("root_folder_id") or "root")
    second_root = str(second_config.get("root_folder_id") or "root")
    if first_root != second_root:
        # Folder IDs do not encode ancestry. Once the drive is known to be the
        # same, treating distinct roots as potentially nested avoids deleting
        # through a second mount alias.
        return True
    first_path = normalize_path(first_relative)
    second_path = normalize_path(second_relative)
    return _path_overlaps(first_path, second_path)


def mount_paths_overlap(mounts, first_path, second_path):
    """Return whether two TaoSync paths may address overlapping backend data."""
    lookup = _mount_lookup(mounts)
    first_mount, first_relative = _resolve_mount(lookup, first_path)
    second_mount, second_relative = _resolve_mount(lookup, second_path)
    if first_mount is None or second_mount is None:
        return False
    first_type = str(first_mount.get("driverType") or "").strip().lower()
    second_type = str(second_mount.get("driverType") or "").strip().lower()
    if first_type != second_type:
        return False
    first_config = first_mount.get("config") or {}
    second_config = second_mount.get("config") or {}

    if first_type == "local":
        return _local_paths_overlap(
            first_config, first_relative, second_config, second_relative
        )
    if first_type == "smb":
        first = _smb_descriptor(first_config, first_relative)
        second = _smb_descriptor(second_config, second_relative)
    elif first_type in ("ftp", "sftp"):
        first = _remote_descriptor(first_type, first_config, first_relative)
        second = _remote_descriptor(second_type, second_config, second_relative)
    elif first_type == "aliyun":
        return _aliyun_paths_overlap(
            first_config, first_relative, second_config, second_relative
        )
    else:
        return False

    if first is None or second is None or first[0] != second[0]:
        return False
    return _path_overlaps(first[1], second[1], separator="\\" if first_type == "smb" else "/")
