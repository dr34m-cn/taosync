import base64
import hashlib
import io
import posixpath
import stat
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from service.storage import storageService
from service.storage.drivers.base import TransferCancelled
from service.storage.drivers.sftp import SftpDriver
from service.storage.factory import SECRET_FIELDS, createDriver, getDriverTypes


_SERVER_KEY_BLOB = b"server-public-key"
_HOST_FINGERPRINT = "SHA256:" + base64.b64encode(
    hashlib.sha256(_SERVER_KEY_BLOB).digest()
).decode("ascii").rstrip("=")


class _MemoryFile(io.BytesIO):
    def __init__(self, initial=b"", save=None):
        super().__init__(initial)
        self.save = save

    def close(self):
        if self.save is not None and not self.closed:
            self.save(self.getvalue())
        super().close()


class _FakeSftp:
    def __init__(self):
        self.nodes = {
            "/": {"kind": "dir"},
            "/srv": {"kind": "dir"},
        }
        self.posix_rename_supported = True

    @staticmethod
    def _path(path):
        return posixpath.normpath(path)

    def normalize(self, path):
        return self._path(path)

    def _attr(self, path, filename=None):
        node = self.nodes[self._path(path)]
        modes = {
            "dir": stat.S_IFDIR | 0o755,
            "file": stat.S_IFREG | 0o644,
            "link": stat.S_IFLNK | 0o777,
        }
        return SimpleNamespace(
            filename=filename,
            st_mode=modes[node["kind"]],
            st_size=len(node.get("data", b"")),
            st_mtime=node.get("mtime", 1),
        )

    def lstat(self, path):
        path = self._path(path)
        if path not in self.nodes:
            raise FileNotFoundError(2, "missing", path)
        return self._attr(path)

    def listdir_attr(self, path):
        path = self._path(path)
        prefix = path.rstrip("/") + "/"
        result = []
        for child in sorted(self.nodes):
            if child == path or not child.startswith(prefix):
                continue
            relative = child[len(prefix):]
            if "/" not in relative:
                result.append(self._attr(child, relative))
        return result

    def mkdir(self, path):
        path = self._path(path)
        if path in self.nodes:
            raise FileExistsError(path)
        if self.nodes.get(posixpath.dirname(path), {}).get("kind") != "dir":
            raise FileNotFoundError(posixpath.dirname(path))
        self.nodes[path] = {"kind": "dir"}

    def open(self, path, mode):
        path = self._path(path)
        if len(posixpath.basename(path).encode("utf-8")) > 255:
            raise OSError("file name too long")
        if mode == "rb":
            return _MemoryFile(self.nodes[path]["data"])
        if "w" in mode:
            if "x" in mode and path in self.nodes:
                raise FileExistsError(path)
            return _MemoryFile(
                save=lambda data: self.nodes.__setitem__(
                    path, {"kind": "file", "data": data}
                )
            )
        raise AssertionError("unexpected mode: " + mode)

    def posix_rename(self, source, destination):
        if not self.posix_rename_supported:
            raise OSError("posix-rename unsupported")
        source = self._path(source)
        destination = self._path(destination)
        self.nodes[destination] = self.nodes.pop(source)

    def rename(self, source, destination):
        source = self._path(source)
        destination = self._path(destination)
        if destination in self.nodes:
            raise FileExistsError(destination)
        self.nodes[destination] = self.nodes.pop(source)

    def remove(self, path):
        path = self._path(path)
        if path not in self.nodes:
            raise FileNotFoundError(path)
        if self.nodes[path]["kind"] == "dir":
            raise IsADirectoryError(path)
        del self.nodes[path]

    def rmdir(self, path):
        path = self._path(path)
        if self.listdir_attr(path):
            raise OSError("directory not empty")
        del self.nodes[path]


def _config(**updates):
    config = {
        "host": "sftp.test",
        "port": 22,
        "username": "sync-user",
        "auth_type": "password",
        "password": "secret",
        "root_path": "/srv",
        "host_key_fingerprint": _HOST_FINGERPRINT,
    }
    config.update(updates)
    return config


class SftpDriverTests(unittest.TestCase):
    def _mounted(self, fake=None, **config):
        fake = fake or _FakeSftp()
        driver = SftpDriver(_config(**config))

        @contextmanager
        def connected():
            yield fake

        return driver, fake, patch.object(driver, "_connect", side_effect=connected)

    def test_factory_and_secret_fields_include_sftp(self):
        self.assertIn("sftp", getDriverTypes())
        self.assertEqual(
            SECRET_FIELDS["sftp"],
            {"password", "private_key", "private_key_passphrase"},
        )
        self.assertIsInstance(createDriver("sftp", _config()), SftpDriver)

        sanitized = storageService._sanitized(
            {
                "driverType": "sftp",
                "config": {
                    "password": "password",
                    "private_key": "private-key",
                    "private_key_passphrase": "passphrase",
                    "host": "sftp.test",
                },
            }
        )
        self.assertEqual(sanitized["config"]["password"], "")
        self.assertEqual(sanitized["config"]["private_key"], "")
        self.assertEqual(sanitized["config"]["private_key_passphrase"], "")
        self.assertEqual(
            sanitized["secretState"],
            {
                "password": True,
                "private_key": True,
                "private_key_passphrase": True,
            },
        )

    def test_mount_update_preserves_redacted_sftp_secrets(self):
        old = {
            "id": 71,
            "engineId": 1,
            "name": "ssh-files",
            "driverType": "sftp",
            "config": {
                **_config(auth_type="private_key", password="fallback"),
                "private_key": "private-key",
                "private_key_passphrase": "passphrase",
            },
            "enabled": 1,
            "authVersion": 1,
        }
        captured = {}
        with patch.object(
            storageService.storageMapper, "getMountById", return_value=old
        ), patch.object(storageService, "_requireTaoSync"), patch.object(
            storageService,
            "_normalizeDriverConfig",
            side_effect=lambda _driver_type, config: config,
        ), patch.object(
            storageService.storageMapper,
            "updateMount",
            side_effect=lambda row: captured.update(row),
        ), patch.object(storageService, "_invalidateEngine"):
            storageService.updateMount(
                {
                    "id": 71,
                    "name": "ssh-files",
                    "driverType": "sftp",
                    "config": {
                        "auth_type": "private_key",
                        "password": "",
                        "private_key": "",
                        "private_key_passphrase": "",
                    },
                }
            )

        self.assertEqual(captured["config"]["password"], "")
        self.assertEqual(captured["config"]["private_key"], "private-key")
        self.assertEqual(
            captured["config"]["private_key_passphrase"], "passphrase"
        )

    def test_mount_add_discards_inactive_sftp_secrets(self):
        captured = {}
        with patch.object(storageService, "_requireTaoSync"), patch.object(
            storageService, "_validateUniqueName"
        ), patch.object(
            storageService,
            "_normalizeDriverConfig",
            side_effect=lambda _driver_type, config: config,
        ), patch.object(
            storageService.storageMapper,
            "addMount",
            side_effect=lambda row: captured.update(row) or 72,
        ), patch.object(storageService, "_invalidateEngine"):
            storageService.addMount(
                {
                    "engineId": 1,
                    "name": "ssh-files",
                    "driverType": "sftp",
                    "config": {
                        **_config(auth_type="private_key"),
                        "password": "inactive-password",
                        "private_key": "active-private-key",
                        "private_key_passphrase": "active-passphrase",
                    },
                }
            )

        self.assertEqual(captured["config"]["password"], "")
        self.assertEqual(captured["config"]["private_key"], "active-private-key")
        self.assertEqual(
            captured["config"]["private_key_passphrase"], "active-passphrase"
        )

    def test_probe_reuses_redacted_secrets_without_writing_mount(self):
        old = {
            "id": 71,
            "engineId": 1,
            "name": "ssh-files",
            "driverType": "sftp",
            "config": {
                **_config(auth_type="private_key", password=""),
                "private_key": "stored-private-key",
                "private_key_passphrase": "stored-passphrase",
            },
            "enabled": 1,
        }
        expected = {
            "fingerprint": _HOST_FINGERPRINT,
            "rootPath": "/srv",
            "directories": [{"name": "srv", "path": "/srv"}],
        }
        probe = MagicMock()
        probe.probe.return_value = expected

        with patch.object(storageService, "_requireTaoSync") as require_engine, patch.object(
            storageService.storageMapper, "getMountById", return_value=old
        ), patch.object(
            storageService, "createDriver", return_value=probe
        ) as create_driver, patch.object(
            storageService.storageMapper, "addMount"
        ) as add_mount, patch.object(
            storageService.storageMapper, "updateMount"
        ) as update_mount, patch.object(
            storageService.storageMapper, "removeMount"
        ) as remove_mount, patch.object(
            storageService, "_invalidateEngine"
        ) as invalidate:
            result = storageService.testSftp(
                {
                    "engineId": 1,
                    "mountId": 71,
                    "config": {
                        "auth_type": "private_key",
                        "private_key": "",
                        "private_key_passphrase": "",
                        "password": "",
                        "root_path": "/srv",
                    },
                }
            )

        self.assertEqual(result, expected)
        require_engine.assert_called_once_with(1)
        create_driver.assert_called_once()
        driver_type, config = create_driver.call_args.args
        self.assertEqual(driver_type, "sftp")
        self.assertEqual(config["private_key"], "stored-private-key")
        self.assertEqual(config["private_key_passphrase"], "stored-passphrase")
        self.assertEqual(config["password"], "")
        add_mount.assert_not_called()
        update_mount.assert_not_called()
        remove_mount.assert_not_called()
        invalidate.assert_not_called()

    def test_probe_rejects_mount_from_another_engine_or_driver(self):
        base = {
            "id": 71,
            "engineId": 2,
            "driverType": "sftp",
            "config": _config(),
        }
        with patch.object(storageService, "_requireTaoSync"), patch.object(
            storageService.storageMapper, "getMountById", return_value=base
        ), patch.object(storageService, "createDriver") as create_driver:
            with self.assertRaisesRegex(ValueError, "selected engine"):
                storageService.testSftp(
                    {"engineId": 1, "mountId": 71, "config": {}}
                )
            create_driver.assert_not_called()

        base["engineId"] = 1
        base["driverType"] = "ftp"
        with patch.object(storageService, "_requireTaoSync"), patch.object(
            storageService.storageMapper, "getMountById", return_value=base
        ), patch.object(storageService, "createDriver") as create_driver:
            with self.assertRaisesRegex(ValueError, "not an SFTP"):
                storageService.testSftp(
                    {"engineId": 1, "mountId": 71, "config": {}}
                )
            create_driver.assert_not_called()

    def test_probe_does_not_forward_old_credentials_to_a_new_identity(self):
        old = {
            "id": 71,
            "engineId": 1,
            "driverType": "sftp",
            "config": _config(password="stored-password"),
        }
        with patch.object(storageService, "_requireTaoSync"), patch.object(
            storageService.storageMapper, "getMountById", return_value=old
        ), patch.object(storageService, "createDriver") as create_driver:
            with self.assertRaisesRegex(ValueError, "password is required"):
                storageService.testSftp(
                    {
                        "engineId": 1,
                        "mountId": 71,
                        "config": {"host": "different.example", "password": ""},
                    }
                )
            create_driver.assert_not_called()

    def test_browse_reuses_redacted_secret_without_persisting_mount(self):
        old = {
            "id": 71,
            "engineId": 1,
            "driverType": "sftp",
            "config": _config(password="stored-password"),
        }
        expected = {
            "fingerprint": _HOST_FINGERPRINT,
            "rootPath": "/srv",
            "path": "/srv/Alpha",
            "directories": [{"name": "nested", "path": "/srv/Alpha/nested"}],
        }
        driver = MagicMock()
        driver.browse.return_value = expected

        with patch.object(storageService, "_requireTaoSync"), patch.object(
            storageService.storageMapper, "getMountById", return_value=old
        ), patch.object(
            storageService, "createDriver", return_value=driver
        ) as create_driver, patch.object(
            storageService.storageMapper, "addMount"
        ) as add_mount, patch.object(
            storageService.storageMapper, "updateMount"
        ) as update_mount, patch.object(
            storageService, "_invalidateEngine"
        ) as invalidate:
            result = storageService.browseSftp(
                {
                    "engineId": 1,
                    "mountId": 71,
                    "path": "/srv/Alpha",
                    "config": {
                        "host": "sftp.test",
                        "port": 22,
                        "username": "sync-user",
                        "auth_type": "password",
                        "password": "",
                        "root_path": "/srv",
                    },
                }
            )

        self.assertEqual(result, expected)
        create_driver.assert_called_once()
        self.assertEqual(create_driver.call_args.args[1]["password"], "stored-password")
        driver.browse.assert_called_once_with("/srv/Alpha")
        add_mount.assert_not_called()
        update_mount.assert_not_called()
        invalidate.assert_not_called()

    def test_browse_does_not_reuse_old_secret_for_changed_identity(self):
        old = {
            "id": 71,
            "engineId": 1,
            "driverType": "sftp",
            "config": _config(password="stored-password"),
        }
        with patch.object(storageService, "_requireTaoSync"), patch.object(
            storageService.storageMapper, "getMountById", return_value=old
        ), patch.object(storageService, "createDriver") as create_driver:
            with self.assertRaisesRegex(ValueError, "password is required"):
                storageService.browseSftp(
                    {
                        "engineId": 1,
                        "mountId": 71,
                        "path": "/srv",
                        "config": {
                            "host": "different.example",
                            "password": "",
                            "root_path": "/srv",
                        },
                    }
                )
            create_driver.assert_not_called()

    def test_browse_requires_path(self):
        with patch.object(storageService, "_requireTaoSync") as require_engine, patch.object(
            storageService, "createDriver"
        ) as create_driver, self.assertRaisesRegex(ValueError, "path is required"):
            storageService.browseSftp(
                {"engineId": 1, "config": _config()}
            )
        require_engine.assert_not_called()
        create_driver.assert_not_called()

    def test_new_private_key_does_not_inherit_old_passphrase(self):
        old = {
            "id": 71,
            "engineId": 1,
            "driverType": "sftp",
            "config": {
                **_config(auth_type="private_key", password=""),
                "private_key": "stored-private-key",
                "private_key_passphrase": "stored-passphrase",
            },
        }
        probe = MagicMock()
        probe.probe.return_value = {"directories": []}
        with patch.object(storageService, "_requireTaoSync"), patch.object(
            storageService.storageMapper, "getMountById", return_value=old
        ), patch.object(
            storageService, "createDriver", return_value=probe
        ) as create_driver:
            storageService.testSftp(
                {
                    "engineId": 1,
                    "mountId": 71,
                    "config": {
                        "auth_type": "private_key",
                        "private_key": "new-private-key",
                        "private_key_passphrase": "",
                    },
                }
            )

        config = create_driver.call_args.args[1]
        self.assertEqual(config["private_key"], "new-private-key")
        self.assertEqual(config["private_key_passphrase"], "")

    def test_configuration_requires_selected_authentication_method(self):
        with self.assertRaisesRegex(ValueError, "password is required"):
            SftpDriver(_config(password=""))
        with self.assertRaisesRegex(ValueError, "private_key is required"):
            SftpDriver(_config(auth_type="private_key", password="", private_key=""))
        with self.assertRaisesRegex(ValueError, "dot segments"):
            SftpDriver(_config(root_path="/srv/../outside"))
        with self.assertRaisesRegex(ValueError, "SHA256"):
            SftpDriver(_config(host_key_fingerprint="aa:bb:cc"))
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            SftpDriver(_config(host_key_fingerprint="SHA256:not-valid"))

    def test_empty_host_fingerprint_is_allowed_and_actual_value_is_returned(self):
        driver = SftpDriver(_config(host_key_fingerprint=""))
        server_key = MagicMock()
        server_key.asbytes.return_value = _SERVER_KEY_BLOB

        self.assertEqual(driver._verify_host_key(server_key), _HOST_FINGERPRINT)

    def test_probe_returns_actual_fingerprint_root_and_directories_only(self):
        fake = _FakeSftp()
        fake.nodes.update(
            {
                "/srv/zeta": {"kind": "dir"},
                "/srv/Alpha": {"kind": "dir"},
                "/srv/Alpha/nested": {"kind": "dir"},
                "/srv/file.txt": {"kind": "file", "data": b"not a directory"},
                "/srv/link": {"kind": "link"},
            }
        )
        driver = SftpDriver(_config(host_key_fingerprint=""))

        @contextmanager
        def connected():
            driver._connected_host_key_fingerprint = _HOST_FINGERPRINT
            yield fake

        with patch.object(driver, "_connect", side_effect=connected):
            result = driver.probe()

        self.assertEqual(result["fingerprint"], _HOST_FINGERPRINT)
        self.assertEqual(result["rootPath"], "/srv")
        self.assertEqual(
            result["directories"],
            [
                {"name": "srv", "path": "/srv"},
                {"name": "Alpha", "path": "/srv/Alpha"},
                {"name": "zeta", "path": "/srv/zeta"},
            ],
        )

    def test_browse_lists_nested_directories_one_level_at_a_time(self):
        fake = _FakeSftp()
        fake.nodes.update(
            {
                "/srv/Alpha": {"kind": "dir"},
                "/srv/Alpha/zeta": {"kind": "dir"},
                "/srv/Alpha/Beta": {"kind": "dir"},
                "/srv/Alpha/Beta/deep": {"kind": "dir"},
                "/srv/Alpha/file.txt": {"kind": "file", "data": b"file"},
                "/srv/Alpha/link": {"kind": "link"},
            }
        )
        driver = SftpDriver(_config(host_key_fingerprint=""))

        @contextmanager
        def connected():
            driver._connected_host_key_fingerprint = _HOST_FINGERPRINT
            yield fake

        with patch.object(driver, "_connect", side_effect=connected):
            result = driver.browse("/srv/Alpha")

        self.assertEqual(result["fingerprint"], _HOST_FINGERPRINT)
        self.assertEqual(result["rootPath"], "/srv")
        self.assertEqual(result["path"], "/srv/Alpha")
        self.assertEqual(
            result["directories"],
            [
                {"name": "Beta", "path": "/srv/Alpha/Beta"},
                {"name": "zeta", "path": "/srv/Alpha/zeta"},
            ],
        )

    def test_browse_does_not_silently_truncate_large_directory(self):
        fake = _FakeSftp()
        fake.nodes.update(
            {
                "/srv/directory-{:03d}".format(index): {"kind": "dir"}
                for index in range(SftpDriver.probe_directory_limit + 1)
            }
        )
        driver, _fake, mounted = self._mounted(fake)
        with mounted:
            result = driver.browse("/srv")

        self.assertEqual(
            len(result["directories"]), SftpDriver.probe_directory_limit + 1
        )
        self.assertEqual(result["directories"][-1]["name"], "directory-500")

    def test_browse_rejects_paths_outside_root_and_symbolic_link_ancestors(self):
        fake = _FakeSftp()
        fake.nodes.update(
            {
                "/srv/link": {"kind": "link"},
                "/srv/link/child": {"kind": "dir"},
            }
        )
        driver, _fake, mounted = self._mounted(fake)
        with mounted:
            with self.assertRaisesRegex(ValueError, "escapes SFTP root"):
                driver.browse("/outside")
        with mounted:
            with self.assertRaisesRegex(ValueError, "symbolic links"):
                driver.browse("/srv/link/child")

    def test_private_key_authentication_and_connection_resources_are_closed(self):
        private_key = "-----BEGIN OPENSSH PRIVATE KEY-----\nkey\n-----END OPENSSH PRIVATE KEY-----"
        driver = SftpDriver(
            _config(
                auth_type="private_key",
                password="",
                private_key=private_key,
                private_key_passphrase="key-password",
                host_key_fingerprint=_HOST_FINGERPRINT,
            )
        )
        sock = MagicMock(name="socket")
        transport = MagicMock(name="transport")
        transport.get_remote_server_key.return_value.asbytes.return_value = _SERVER_KEY_BLOB
        transport.is_authenticated.return_value = True
        sftp = MagicMock(name="sftp")
        pkey = MagicMock(name="private-key")

        def load_key(file_obj, password=None):
            self.assertEqual(file_obj.read(), private_key)
            self.assertEqual(password, "key-password")
            return pkey

        paramiko = SimpleNamespace(
            AuthenticationException=RuntimeError,
            RSAKey=SimpleNamespace(from_private_key=load_key),
            Transport=MagicMock(return_value=transport),
            SFTPClient=SimpleNamespace(from_transport=MagicMock(return_value=sftp)),
        )
        with patch.object(driver, "_paramiko", return_value=paramiko), patch(
            "service.storage.drivers.sftp.socket.create_connection", return_value=sock
        ):
            with driver._connect() as connected:
                self.assertIs(connected, sftp)

        transport.auth_publickey.assert_called_once_with("sync-user", pkey)
        transport.auth_password.assert_not_called()
        sftp.close.assert_called_once()
        transport.close.assert_called_once()
        sock.close.assert_called_once()

    def test_wrong_server_host_key_is_rejected(self):
        driver = SftpDriver(_config())
        server_key = MagicMock()
        server_key.asbytes.return_value = b"different-server-key"
        with self.assertRaisesRegex(ValueError, "does not match"):
            driver._verify_host_key(server_key)

    def test_password_authentication_failure_closes_transport_and_socket(self):
        driver = SftpDriver(_config())
        sock = MagicMock(name="socket")
        transport = MagicMock(name="transport")
        transport.get_remote_server_key.return_value.asbytes.return_value = _SERVER_KEY_BLOB
        transport.auth_password.side_effect = RuntimeError("authentication denied")
        paramiko = SimpleNamespace(
            AuthenticationException=RuntimeError,
            Transport=MagicMock(return_value=transport),
            SFTPClient=SimpleNamespace(from_transport=MagicMock()),
        )
        with patch.object(driver, "_paramiko", return_value=paramiko), patch(
            "service.storage.drivers.sftp.socket.create_connection", return_value=sock
        ), self.assertRaisesRegex(RuntimeError, "authentication denied"):
            with driver._connect():
                pass

        transport.auth_password.assert_called_once_with("sync-user", "secret")
        transport.close.assert_called_once()
        sock.close.assert_called_once()

    def test_encrypted_private_key_is_parsed_by_supported_paramiko(self):
        import paramiko

        key = paramiko.RSAKey.generate(1024)
        key_text = io.StringIO()
        key.write_private_key(key_text, password="key-password")
        driver = SftpDriver(
            _config(
                auth_type="private_key",
                password="",
                private_key=key_text.getvalue(),
                private_key_passphrase="key-password",
            )
        )
        parsed = driver._load_private_key(paramiko)
        self.assertEqual(parsed.get_fingerprint(), key.get_fingerprint())

    def test_file_operations_and_streamed_copy(self):
        driver, fake, mounted = self._mounted()
        progress = []
        with mounted:
            driver.mkdir("/nested/child")
            driver.upload(
                "/nested/child/source.bin",
                io.BytesIO(b"payload"),
                size=7,
                progress=progress.append,
            )
            self.assertEqual(
                driver.list("/nested/child"),
                [{"name": "source.bin", "is_dir": False, "size": 7}],
            )
            detailed = driver.list("/nested/child", details=True)
            self.assertTrue(detailed[0]["fingerprint"].startswith("sftp:sha256:"))
            downloaded = io.BytesIO()
            driver.download("/nested/child/source.bin", downloaded)
            self.assertEqual(downloaded.getvalue(), b"payload")

            driver.copy(
                "/nested/child/source.bin",
                "/nested/copied.bin",
                size=7,
            )
            self.assertEqual(fake.nodes["/srv/nested/copied.bin"]["data"], b"payload")
            driver.delete("/nested/child")

        self.assertNotIn("/srv/nested/child", fake.nodes)
        self.assertEqual(progress[-1], 1.0)

    def test_cancelled_upload_preserves_destination_and_removes_temporary(self):
        fake = _FakeSftp()
        fake.nodes["/srv/existing.bin"] = {"kind": "file", "data": b"old"}
        driver, fake, mounted = self._mounted(fake)
        cancel = threading.Event()
        cancel.set()
        with mounted, self.assertRaises(TransferCancelled):
            driver.upload(
                "/existing.bin", io.BytesIO(b"new"), size=3, cancel=cancel
            )
        self.assertEqual(fake.nodes["/srv/existing.bin"]["data"], b"old")
        self.assertFalse(any(".taosync-" in path for path in fake.nodes))

    def test_midstream_cancel_and_size_mismatch_do_not_commit_temporary(self):
        fake = _FakeSftp()
        fake.nodes["/srv/existing.bin"] = {"kind": "file", "data": b"old"}
        driver, fake, mounted = self._mounted(fake)
        cancel = threading.Event()

        class CancelAfterRead(io.BytesIO):
            def read(self, size=-1):
                chunk = super().read(size)
                if chunk:
                    cancel.set()
                return chunk

        with mounted:
            with self.assertRaises(TransferCancelled):
                driver.upload(
                    "/existing.bin",
                    CancelAfterRead(b"new"),
                    size=3,
                    cancel=cancel,
                )
            with self.assertRaisesRegex(IOError, "expected file size"):
                driver.upload("/new.bin", io.BytesIO(b"short"), size=6)

        self.assertEqual(fake.nodes["/srv/existing.bin"]["data"], b"old")
        self.assertNotIn("/srv/new.bin", fake.nodes)
        self.assertFalse(any(".taosync-" in path for path in fake.nodes))

    def test_posix_rename_atomically_overwrites_existing_file(self):
        fake = _FakeSftp()
        fake.nodes["/srv/existing.bin"] = {"kind": "file", "data": b"old"}
        driver, fake, mounted = self._mounted(fake)
        with mounted:
            driver.upload("/existing.bin", io.BytesIO(b"new"), size=3)
        self.assertEqual(fake.nodes["/srv/existing.bin"]["data"], b"new")
        self.assertFalse(any(".taosync-" in path for path in fake.nodes))

    def test_long_destination_name_uses_a_short_sibling_temporary(self):
        driver, fake, mounted = self._mounted()
        name = "a" * 250
        with mounted:
            driver.upload("/" + name, io.BytesIO(b"x"), size=1)
        self.assertEqual(fake.nodes["/srv/" + name]["data"], b"x")

    def test_existing_file_requires_atomic_posix_rename(self):
        fake = _FakeSftp()
        fake.posix_rename_supported = False
        fake.nodes["/srv/existing.bin"] = {"kind": "file", "data": b"old"}
        driver, fake, mounted = self._mounted(fake)
        with mounted, self.assertRaisesRegex(RuntimeError, "POSIX rename"):
            driver.upload("/existing.bin", io.BytesIO(b"new"), size=3)
        self.assertEqual(fake.nodes["/srv/existing.bin"]["data"], b"old")
        self.assertFalse(any(".taosync-" in path for path in fake.nodes))

    def test_paths_and_symbolic_links_cannot_escape_mount(self):
        fake = _FakeSftp()
        fake.nodes["/srv/link"] = {"kind": "link"}
        driver, _fake, mounted = self._mounted(fake)
        with mounted:
            with self.assertRaises(ValueError):
                driver.list("/../outside")
            with self.assertRaisesRegex(ValueError, "symbolic links"):
                driver.download("/link/file.bin", io.BytesIO())


if __name__ == "__main__":
    unittest.main()
