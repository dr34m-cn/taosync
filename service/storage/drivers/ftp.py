import ftplib
import posixpath
import ssl
import uuid
from contextlib import contextmanager

from common.fileFingerprint import fileFingerprint

from .base import StorageDriver, check_cancel, normalize_path


class FtpDriver(StorageDriver):
    driver_type = "ftp"

    def __init__(self, config):
        self.host = str(config.get("host") or "").strip()
        if not self.host or any(ord(char) < 32 or ord(char) == 127 for char in self.host):
            raise ValueError("FTP host is required")
        # `tls` means explicit AUTH TLS, whose standard port remains 21.
        self.port = int(config.get("port") or 21)
        self.username = str(config.get("username") or "anonymous")
        self.password = str(config.get("password") or "")
        if any(
            any(ord(char) < 32 or ord(char) == 127 for char in value)
            for value in (self.username, self.password)
        ):
            raise ValueError("FTP credentials cannot contain control characters")
        self.timeout = int(config.get("timeout") or 60)
        self.passive = bool(config.get("passive", True))
        self.tls = bool(config.get("tls", False))
        root = str(config.get("root_path") or "/").replace("\\", "/")
        if any(part in (".", "..") for part in root.split("/") if part):
            raise ValueError("FTP root_path cannot contain dot segments")
        if any(ord(char) < 32 or ord(char) == 127 for char in root):
            raise ValueError("FTP root_path cannot contain control characters")
        self.root = "/" + root.strip("/") if root.strip("/") else "/"

    @contextmanager
    def _connect(self):
        if self.tls:
            ftp = ftplib.FTP_TLS(timeout=self.timeout, context=ssl.create_default_context())
        else:
            ftp = ftplib.FTP(timeout=self.timeout)
        try:
            ftp.connect(self.host, self.port)
            ftp.login(self.username, self.password)
            if self.tls:
                ftp.prot_p()
            ftp.set_pasv(self.passive)
            yield ftp
        finally:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass

    def _remote(self, path, allow_root=True):
        path = normalize_path(path, allow_root=allow_root)
        if any(ord(char) < 32 or ord(char) == 127 for char in path):
            raise ValueError("FTP paths cannot contain control characters")
        remote = posixpath.normpath(posixpath.join(self.root, path.lstrip("/")))
        root_prefix = self.root.rstrip("/") + "/"
        if remote != self.root and not (remote + "/").startswith(root_prefix):
            raise ValueError("path escapes FTP root")
        return remote

    def _entries(self, ftp, remote, details=False):
        result = []
        try:
            for name, facts in ftp.mlsd(remote):
                if name in (".", ".."):
                    continue
                item_type = facts.get("type", "")
                if item_type in ("cdir", "pdir"):
                    continue
                if item_type not in ("dir", "file"):
                    # Symlinks and server-specific reparse entries are not
                    # safe to expose through a root-isolated mount.
                    continue
                is_dir = item_type == "dir"
                size = None if is_dir else (
                    int(facts["size"]) if facts.get("size") is not None
                    else self._file_size(ftp, posixpath.join(remote, name))
                )
                item = {
                    "name": name,
                    "is_dir": is_dir,
                    "size": size,
                }
                if details:
                    item["fingerprint"] = fileFingerprint(
                        "ftp", facts.get("unique"), facts.get("modify")
                    )
                result.append(item)
            return result
        except (AttributeError, ftplib.all_errors) as exc:
            # NLST + cwd cannot distinguish an ordinary directory from a
            # symlink on many FTP servers. Refusing that fallback keeps the
            # configured root an actual security boundary.
            raise RuntimeError(
                "FTP server must support MLSD for a root-isolated mount"
            ) from exc

    @staticmethod
    def _file_size(ftp, remote):
        try:
            ftp.voidcmd("TYPE I")
            size = ftp.size(remote)
        except ftplib.all_errors as exc:
            raise RuntimeError("FTP server cannot report file size for {}".format(remote)) from exc
        if size is None:
            raise RuntimeError("FTP server returned an unknown file size for {}".format(remote))
        return int(size)

    def list(self, path, details=False):
        remote = self._remote(path)
        with self._connect() as ftp:
            self._assert_root_directory(ftp)
            result = self._entries(ftp, remote, details)
        result.sort(key=lambda x: (not x["is_dir"], x["name"].casefold()))
        return result

    def mkdir(self, path):
        remote = self._remote(path)
        with self._connect() as ftp:
            self._assert_root_directory(ftp)
            self._ensure_directory(ftp, remote)

    def _assert_root_directory(self, ftp):
        if self.root == "/":
            return
        kind = self._path_kind(ftp, self.root)
        if kind == "dir":
            return
        if kind == "unsafe":
            raise ValueError("FTP mount root is a symbolic link or unknown entry")
        raise FileNotFoundError(self.root)

    @staticmethod
    def _ensure_directory(ftp, remote):
        """Create a directory path without following unknown FTP entries."""
        if remote == "/":
            return
        current = "/"
        for part in remote.strip("/").split("/"):
            current = posixpath.join(current, part)
            kind = FtpDriver._path_kind(ftp, current)
            if kind == "dir":
                continue
            if kind == "unsafe":
                raise ValueError("FTP symbolic links and unknown entry types are not supported")
            if kind == "file":
                raise NotADirectoryError(current)
            try:
                ftp.mkd(current)
            except ftplib.all_errors:
                # A concurrent creator is fine only when MLSD confirms it is
                # an ordinary directory.
                if FtpDriver._path_kind(ftp, current) != "dir":
                    raise
            if FtpDriver._path_kind(ftp, current) != "dir":
                raise RuntimeError("FTP server did not create a verifiable directory")

    def _delete(self, ftp, remote):
        kind = self._path_kind(ftp, remote)
        if kind == "file":
            ftp.delete(remote)
            return
        if kind == "unsafe":
            raise ValueError("FTP symbolic links and unknown entry types are not supported")
        if kind is None:
            raise FileNotFoundError(remote)
        for item in self._entries(ftp, remote):
            child = posixpath.join(remote, item["name"])
            if item["is_dir"]:
                self._delete(ftp, child)
            else:
                ftp.delete(child)
        ftp.rmd(remote)

    def delete(self, path):
        remote = self._remote(path, allow_root=False)
        with self._connect() as ftp:
            self._assert_root_directory(ftp)
            self._delete(ftp, remote)

    def download(self, path, target, progress=None, cancel=None):
        remote = self._remote(path, allow_root=False)
        with self._connect() as ftp:
            self._assert_root_directory(ftp)
            kind = self._path_kind(ftp, remote)
            if kind == "dir":
                raise IsADirectoryError(path)
            if kind == "unsafe":
                raise ValueError("FTP symbolic links and unknown entry types are not supported")
            if kind is None:
                raise FileNotFoundError(path)
            size = self._file_size(ftp, remote)
            done = 0

            def receive(chunk):
                nonlocal done
                check_cancel(cancel)
                target.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done / size if size else 0.0)

            ftp.retrbinary("RETR " + remote, receive, blocksize=1024 * 1024)
            if done != size:
                raise IOError("FTP download ended before the expected file size")
            if progress:
                progress(1.0)

    def upload(self, path, source, size=None, progress=None, cancel=None):
        remote = self._remote(path, allow_root=False)
        parent = posixpath.dirname(remote)
        # Ensure nested destinations created by a job are accepted by FTP
        # servers that do not create parent directories implicitly.
        with self._connect() as ftp:
            self._assert_root_directory(ftp)
            self._ensure_directory(ftp, parent)
        with self._connect() as ftp:
            self._assert_root_directory(ftp)
            temporary = remote + ".taosync-" + uuid.uuid4().hex + ".part"
            done = 0

            def sent(chunk):
                nonlocal done
                check_cancel(cancel)
                done += len(chunk)
                if progress:
                    progress(done / size if size else 0.0)

            try:
                check_cancel(cancel)
                ftp.storbinary("STOR " + temporary, source, blocksize=1024 * 1024, callback=sent)
                if size is not None and done != int(size):
                    raise IOError("source stream ended before the expected file size")
                check_cancel(cancel)
                self._replace_file(ftp, temporary, remote)
                if progress:
                    progress(1.0)
            finally:
                try:
                    ftp.delete(temporary)
                except ftplib.all_errors:
                    pass

    @staticmethod
    def _replace_file(ftp, temporary, destination):
        kind = FtpDriver._path_kind(ftp, destination)
        if kind == "dir":
            raise IsADirectoryError(destination)
        try:
            ftp.rename(temporary, destination)
            return
        except ftplib.all_errors as first_error:
            kind = FtpDriver._path_kind(ftp, destination)
            if kind == "dir":
                raise IsADirectoryError(destination) from first_error
            if kind != "file":
                raise first_error
            backup = destination + ".taosync-backup-" + uuid.uuid4().hex
            try:
                ftp.rename(destination, backup)
            except ftplib.all_errors:
                raise first_error
            try:
                ftp.rename(temporary, destination)
            except BaseException:
                try:
                    ftp.rename(backup, destination)
                except ftplib.all_errors:
                    pass
                raise
            try:
                ftp.delete(backup)
            except ftplib.all_errors:
                pass

    @staticmethod
    def _path_kind(ftp, path):
        parent = posixpath.dirname(path) or "/"
        name = posixpath.basename(path.rstrip("/"))
        try:
            for entry_name, facts in ftp.mlsd(parent):
                if entry_name != name:
                    continue
                item_type = facts.get("type")
                if item_type == "dir":
                    return "dir"
                if item_type == "file":
                    return "file"
                return "unsafe"
        except (AttributeError, ftplib.all_errors) as exc:
            raise RuntimeError(
                "FTP server must support MLSD for a root-isolated mount"
            ) from exc
