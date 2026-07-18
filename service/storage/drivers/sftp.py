import base64
import hashlib
import hmac
import io
import math
import posixpath
import socket
import stat
import uuid
from contextlib import contextmanager

from common.fileFingerprint import fileFingerprint

from .base import StorageDriver, check_cancel, normalize_path


class SftpDriver(StorageDriver):
    driver_type = "sftp"
    probe_directory_limit = 500

    def __init__(self, config):
        self.host = str(config.get("host") or "").strip()
        self.port = int(config.get("port") or 22)
        self.username = str(config.get("username") or "").strip()
        self.password = str(config.get("password") or "")
        self.private_key = str(config.get("private_key") or "")
        self.private_key_passphrase = str(config.get("private_key_passphrase") or "")
        self.auth_type = str(
            config.get("auth_type") or ("private_key" if self.private_key else "password")
        ).strip().lower()
        self.timeout = float(config.get("timeout") or 30)
        self.host_key_fingerprint = str(
            config.get("host_key_fingerprint") or ""
        ).strip()
        self._connected_host_key_fingerprint = ""

        if not self.host or self._has_control(self.host) or any(
            char in self.host for char in "/\\"
        ):
            raise ValueError("SFTP host is required")
        if not 1 <= self.port <= 65535:
            raise ValueError("SFTP port must be between 1 and 65535")
        if not self.username or self._has_control(self.username):
            raise ValueError("SFTP username is required")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("SFTP timeout must be greater than zero")
        if self.auth_type not in ("password", "private_key"):
            raise ValueError("SFTP auth_type must be password or private_key")
        if self.auth_type == "password" and not self.password:
            raise ValueError("SFTP password is required for password authentication")
        if self.auth_type == "private_key" and not self.private_key.strip():
            raise ValueError("SFTP private_key is required for private key authentication")

        root = str(config.get("root_path") or "/").replace("\\", "/")
        if any(part in (".", "..") for part in root.split("/") if part):
            raise ValueError("SFTP root_path cannot contain dot segments")
        if self._has_control(root):
            raise ValueError("SFTP root_path cannot contain control characters")
        self.root = "/" + root.strip("/") if root.strip("/") else "/"

        if self.host_key_fingerprint:
            self._validate_host_key_fingerprint(self.host_key_fingerprint)

    @staticmethod
    def _has_control(value):
        return any(ord(char) < 32 or ord(char) == 127 for char in value)

    @staticmethod
    def _validate_host_key_fingerprint(fingerprint):
        if not fingerprint.startswith("SHA256:"):
            raise ValueError("SFTP host_key_fingerprint must use SHA256 format")
        encoded = fingerprint[7:].rstrip("=")
        try:
            decoded = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), validate=True
            )
        except ValueError as exc:
            raise ValueError("invalid SFTP SHA256 host key fingerprint") from exc
        if len(decoded) != hashlib.sha256().digest_size:
            raise ValueError("invalid SFTP SHA256 host key fingerprint")

    @staticmethod
    def _paramiko():
        try:
            import paramiko
        except ImportError as exc:
            raise RuntimeError("SFTP support requires the paramiko package") from exc
        return paramiko

    def _load_private_key(self, paramiko):
        if self.auth_type != "private_key":
            return None
        last_error = None
        # PKey is abstract in released Paramiko versions even though it
        # exposes from_private_key. Concrete loaders support both PEM and the
        # OpenSSH private-key envelope without writing secret material to disk.
        key_classes = [
            getattr(paramiko, name, None)
            for name in ("RSAKey", "ECDSAKey", "Ed25519Key", "DSSKey")
        ]
        for key_class in (item for item in key_classes if item is not None):
            try:
                return key_class.from_private_key(
                    io.StringIO(self.private_key),
                    password=self.private_key_passphrase or None,
                )
            except Exception as exc:
                last_error = exc
        raise ValueError("invalid SFTP private key or passphrase") from last_error

    @contextmanager
    def _connect(self):
        paramiko = self._paramiko()
        self._connected_host_key_fingerprint = ""
        sock = None
        transport = None
        sftp = None
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            transport = paramiko.Transport(sock)
            transport.banner_timeout = self.timeout
            transport.auth_timeout = self.timeout
            transport.start_client(timeout=self.timeout)
            self._connected_host_key_fingerprint = self._verify_host_key(
                transport.get_remote_server_key()
            )

            if self.auth_type == "private_key":
                transport.auth_publickey(
                    self.username, self._load_private_key(paramiko)
                )
            else:
                transport.auth_password(self.username, self.password)
            if not transport.is_authenticated():
                raise paramiko.AuthenticationException("SFTP authentication failed")

            sftp = paramiko.SFTPClient.from_transport(transport)
            channel = sftp.get_channel()
            if channel is not None:
                channel.settimeout(self.timeout)
            yield sftp
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass

    def _verify_host_key(self, server_key):
        actual = "SHA256:" + base64.b64encode(
            hashlib.sha256(server_key.asbytes()).digest()
        ).decode("ascii").rstrip("=")
        expected = self.host_key_fingerprint.rstrip("=")
        if expected and not hmac.compare_digest(actual, expected):
            raise ValueError("SFTP server host key fingerprint does not match")
        return actual

    def probe(self):
        """Test authentication and list the configured root and its child dirs."""
        with self._connect() as sftp:
            root = self._canonical_root(sftp)
            children = self._list_directories(sftp, root)
            root_entry = {
                "name": posixpath.basename(root.rstrip("/")) or "/",
                "path": root,
            }
            directories = [root_entry]
            directories.extend(children[: self.probe_directory_limit - 1])
            return {
                "fingerprint": self._connected_host_key_fingerprint,
                "rootPath": root,
                "directories": directories,
            }

    def browse(self, path):
        """List one directory level below an absolute path within the probe root."""
        with self._connect() as sftp:
            root = self._canonical_root(sftp)
            requested = normalize_path(path)
            if self._has_control(requested):
                raise ValueError("SFTP paths cannot contain control characters")
            prefix = root.rstrip("/") + "/"
            if requested != root and not requested.startswith(prefix):
                raise ValueError("path escapes SFTP root")

            relative = posixpath.relpath(requested, root)
            virtual = "/" if relative == "." else "/" + relative
            remote = self._resolve(sftp, virtual, root=root)
            info = sftp.lstat(remote)
            if not stat.S_ISDIR(info.st_mode):
                raise NotADirectoryError(path)
            return {
                "fingerprint": self._connected_host_key_fingerprint,
                "rootPath": root,
                "path": remote,
                "directories": self._list_directories(sftp, remote),
            }

    def _list_directories(self, sftp, remote):
        directories = []
        for item in sftp.listdir_attr(remote):
            if (
                item.filename in (".", "..")
                or "/" in item.filename
                or "\\" in item.filename
                or self._has_control(item.filename)
                or stat.S_ISLNK(item.st_mode)
                or not stat.S_ISDIR(item.st_mode)
            ):
                continue
            directories.append(
                {
                    "name": item.filename,
                    "path": posixpath.normpath(
                        posixpath.join(remote, item.filename)
                    ),
                }
            )
        directories.sort(key=lambda item: (item["name"].casefold(), item["name"]))
        return directories

    def _remote(self, path, allow_root=True):
        path = normalize_path(path, allow_root=allow_root)
        if self._has_control(path):
            raise ValueError("SFTP paths cannot contain control characters")
        remote = posixpath.normpath(posixpath.join(self.root, path.lstrip("/")))
        prefix = self.root.rstrip("/") + "/"
        if remote != self.root and not remote.startswith(prefix):
            raise ValueError("path escapes SFTP root")
        return remote

    @staticmethod
    def _is_missing(exc):
        return isinstance(exc, FileNotFoundError) or getattr(exc, "errno", None) == 2

    def _canonical_root(self, sftp):
        current = "/"
        info = sftp.lstat(current)
        for part in self.root.strip("/").split("/") if self.root != "/" else []:
            current = posixpath.join(current, part)
            info = sftp.lstat(current)
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("SFTP mount root cannot contain symbolic links")
        if not stat.S_ISDIR(info.st_mode):
            raise NotADirectoryError(self.root)
        root = posixpath.normpath(sftp.normalize(self.root))
        if root != posixpath.normpath(self.root):
            raise ValueError("SFTP mount root resolved outside its configured path")
        return root

    def _resolve(self, sftp, path, allow_root=True, allow_missing=False, root=None):
        virtual = normalize_path(path, allow_root=allow_root)
        if self._has_control(virtual):
            raise ValueError("SFTP paths cannot contain control characters")
        relative = virtual.lstrip("/")
        root = root if root is not None else self._canonical_root(sftp)
        remote = posixpath.normpath(posixpath.join(root, relative))
        prefix = root.rstrip("/") + "/"
        if remote != root and not remote.startswith(prefix):
            raise ValueError("path escapes SFTP root")

        current = root
        missing = False
        for part in relative.split("/") if relative else []:
            current = posixpath.join(current, part)
            if missing:
                continue
            try:
                info = sftp.lstat(current)
            except OSError as exc:
                if allow_missing and self._is_missing(exc):
                    missing = True
                    continue
                raise
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("SFTP symbolic links are not supported")
        return remote

    def list(self, path, details=False):
        with self._connect() as sftp:
            remote = self._resolve(sftp, path)
            info = sftp.lstat(remote)
            if not stat.S_ISDIR(info.st_mode):
                raise NotADirectoryError(path)
            result = []
            for item in sftp.listdir_attr(remote):
                if item.filename in (".", "..") or stat.S_ISLNK(item.st_mode):
                    continue
                is_dir = stat.S_ISDIR(item.st_mode)
                if not is_dir and not stat.S_ISREG(item.st_mode):
                    continue
                entry = {
                    "name": item.filename,
                    "is_dir": is_dir,
                    "size": None if is_dir else int(item.st_size),
                }
                if details:
                    entry["fingerprint"] = fileFingerprint(
                            "sftp", getattr(item, "st_mtime", None)
                        )
                result.append(entry)
        result.sort(key=lambda item: (not item["is_dir"], item["name"].casefold()))
        return result

    def mkdir(self, path):
        with self._connect() as sftp:
            remote = self._resolve(sftp, path, allow_missing=True)
            self._ensure_directory(sftp, remote)

    def _ensure_directory(self, sftp, remote):
        root = self._canonical_root(sftp)
        relative = posixpath.relpath(remote, root)
        if relative == ".":
            return
        current = root
        for part in relative.split("/"):
            current = posixpath.join(current, part)
            try:
                info = sftp.lstat(current)
            except OSError as exc:
                if not self._is_missing(exc):
                    raise
                sftp.mkdir(current)
                info = sftp.lstat(current)
            if stat.S_ISLNK(info.st_mode):
                raise ValueError("SFTP symbolic links are not supported")
            if not stat.S_ISDIR(info.st_mode):
                raise NotADirectoryError(current)

    def delete(self, path):
        with self._connect() as sftp:
            remote = self._resolve(sftp, path, allow_root=False)
            self._delete(sftp, remote)

    def _delete(self, sftp, remote):
        info = sftp.lstat(remote)
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("SFTP symbolic links are not supported")
        if not stat.S_ISDIR(info.st_mode):
            sftp.remove(remote)
            return
        entries = list(sftp.listdir_attr(remote))
        if any(stat.S_ISLNK(item.st_mode) for item in entries):
            raise ValueError("SFTP symbolic links are not supported")
        for item in entries:
            child = posixpath.join(remote, item.filename)
            if stat.S_ISDIR(item.st_mode):
                self._delete(sftp, child)
            elif stat.S_ISREG(item.st_mode):
                sftp.remove(child)
            else:
                raise ValueError("SFTP special files are not supported")
        sftp.rmdir(remote)

    def download(self, path, target, progress=None, cancel=None):
        with self._connect() as sftp:
            remote = self._resolve(sftp, path, allow_root=False)
            info = sftp.lstat(remote)
            if stat.S_ISDIR(info.st_mode):
                raise IsADirectoryError(path)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("SFTP special files are not supported")
            size = int(info.st_size)
            done = 0
            with sftp.open(remote, "rb") as source:
                while True:
                    check_cancel(cancel)
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    target.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done / size if size else 1.0)
            if done != size:
                raise IOError("SFTP download ended before the expected file size")
            if progress and size == 0:
                progress(1.0)

    def upload(self, path, source, size=None, progress=None, cancel=None):
        with self._connect() as sftp:
            destination = self._resolve(
                sftp, path, allow_root=False, allow_missing=True
            )
            self._ensure_directory(sftp, posixpath.dirname(destination))
            try:
                destination_info = sftp.lstat(destination)
            except OSError as exc:
                if not self._is_missing(exc):
                    raise
                destination_info = None
            if destination_info is not None:
                if stat.S_ISLNK(destination_info.st_mode):
                    raise ValueError("SFTP symbolic links are not supported")
                if stat.S_ISDIR(destination_info.st_mode):
                    raise IsADirectoryError(path)
                if not stat.S_ISREG(destination_info.st_mode):
                    raise ValueError("SFTP special files are not supported")

            temporary = posixpath.join(
                posixpath.dirname(destination),
                ".taosync-" + uuid.uuid4().hex + ".part",
            )
            done = 0
            try:
                check_cancel(cancel)
                with sftp.open(temporary, "wbx") as target:
                    if hasattr(target, "set_pipelined"):
                        target.set_pipelined(True)
                    while True:
                        check_cancel(cancel)
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done / size if size else 0.0)
                if size is not None and done != int(size):
                    raise IOError("source stream ended before the expected file size")
                check_cancel(cancel)
                self._replace_file(sftp, temporary, destination)
                if progress:
                    progress(1.0)
            finally:
                try:
                    sftp.remove(temporary)
                except Exception:
                    pass

    def _replace_file(self, sftp, temporary, destination):
        try:
            sftp.posix_rename(temporary, destination)
            return
        except OSError as exc:
            try:
                destination_info = sftp.lstat(destination)
            except OSError as missing:
                if not self._is_missing(missing):
                    raise
                sftp.rename(temporary, destination)
                return
            if stat.S_ISDIR(destination_info.st_mode):
                raise IsADirectoryError(destination) from exc
            raise RuntimeError(
                "SFTP server must support POSIX rename for atomic file replacement"
            ) from exc
