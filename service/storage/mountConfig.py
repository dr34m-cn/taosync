"""Validate crypt mount settings and seal their recoverable passphrase."""

import base64
import hmac
import re

from cryptography.fernet import Fernet, InvalidToken

from common.config import getConfig


CRYPT_FIELDS = frozenset(("target_mount_id", "target_path", "encryption_key", "encrypt_dir_names"))
_KEY_PREFIX = "fernet:v1:"


def checkDriverFields(driverType, config):
    if driverType == "crypt":
        if config.keys() - CRYPT_FIELDS:
            raise ValueError("unsupported crypt mount setting")
    elif config.keys() & (CRYPT_FIELDS | {"encrypt_backup"}):
        raise ValueError("encryption settings are only supported on crypt mounts")


def _keyCipher():
    # Domain-separate from the app secret's cookie and session uses.
    secret = getConfig()["server"]["passwdStr"].encode("utf-8")
    key = hmac.digest(secret, b"TaoSync/mount-encryption-key/v1", "sha256")
    return Fernet(base64.urlsafe_b64encode(key))


def getMountEncryptionKey(config):
    """Open a saved encrypted config for its runtime wrapper only; never accept plaintext."""
    sealed = config.get("encryption_key")
    if isinstance(sealed, str) and sealed.startswith(_KEY_PREFIX):
        try:
            return _keyCipher().decrypt(sealed[len(_KEY_PREFIX):].encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError):
            pass
    raise ValueError("cannot open the saved mount encryption key")


def _targetPath(path):
    if (not isinstance(path, str) or not path.strip() or "\\" in path
            or re.search(r"[\x00-\x1f\x7f]", path) or re.match(r"^/?[A-Za-z]:", path)
            or path.startswith("//") or any(part in (".", "..") for part in path.split("/"))):
        raise ValueError("target_path must be a path within the selected mount")
    return "/" + "/".join(part for part in path.split("/") if part)


def cryptConfig(request, old=None):
    checkDriverFields("crypt", request)
    config = {**(old or {}), **request}
    target = config.get("target_mount_id")
    if type(target) is not int or not 0 < target <= 2**63 - 1:
        raise ValueError("target_mount_id must be a positive integer")
    config["target_path"] = _targetPath(config.get("target_path"))
    if not isinstance(config.setdefault("encrypt_dir_names", False), bool):
        raise ValueError("encrypt_dir_names must be a boolean")
    if old is not None:
        if request.get("encryption_key", "") != "" or any(config[k] != old[k] for k in (
                "target_mount_id", "target_path", "encrypt_dir_names")):
            raise ValueError("saved crypt mount settings cannot be changed")
        return dict(old)
    key = config.get("encryption_key")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("crypt mounts require a nonblank encryption_key")
    try:
        clear = key.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("encryption_key must be valid Unicode text") from None
    config["encryption_key"] = _KEY_PREFIX + _keyCipher().encrypt(clear).decode("ascii")
    return config


def backingLocation(driverType, config, runtime=False):
    """Compare effective roots. Runtime token rotation is tied to authVersion."""
    if driverType == "local":
        return str(config.get("root_path") or config.get("path") or "")
    if driverType == "aliyun":
        mode = "service" if config.get("auth_service_url") and not config.get("client_secret") else "direct"
        location = (str(config.get("auth_mode") or mode), str(config.get("drive_type") or "resource"),
                    str(config.get("root_folder_id") or "root"))
        fields = ("api_url", "oauth_url", "auth_service_url", "client_id")
        if not runtime:
            fields += ("drive_id", "refresh_token", "refresh_proof", "access_token")
        return location + tuple(str(config.get(key) or "") for key in fields)
    ports = {"smb": 445, "ftp": 21, "sftp": 22}
    if driverType in ports:
        host = config.get("host") or (config.get("server") if driverType == "smb" else "")
        user = str(config.get("username") or ("anonymous" if driverType == "ftp" else ""))
        location = (str(host or "").strip().lower(), str(config.get("port") or ports[driverType]),
                    str(config.get("root_path") or "").replace("\\", "/").strip("/"))
        if driverType == "smb":
            return (*location, user, str(config.get("domain") or "").strip(),
                    str(config.get("share") or "").strip().strip("\\/"))
        if driverType == "sftp":
            return (*location, user.strip(), str(config.get("host_key_fingerprint") or "").strip())
        return (*location, user, bool(config.get("tls")))
    # Future regular drivers can be targets before their identity fields are known.
    return config
