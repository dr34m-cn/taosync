import io
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock, patch

from common.sqlInit import init_sql
from service.engine.taosyncClient import TaoSyncClient
from service.storage.drivers.aliyun import AliyunDriveDriver
from service.storage.drivers.base import TransferCancelled, stream_transfer
from service.storage.drivers.ftp import FtpDriver
from service.storage.drivers.local import LocalDriver
from service.storage import storageService


class _Response:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


class SqlInitializationTests(unittest.TestCase):
    def _initialize(self, database):
        config = {
            "db": {"dbname": str(database)},
            "server": {"password": "test-password"},
        }
        with patch("common.sqlBase.getConfig", return_value=config), patch(
            "common.sqlInit.getConfig", return_value=config
        ):
            init_sql()

    def _assert_builtin_engine(self, database):
        with closing(sqlite3.connect(database)) as connection:
            rows = connection.execute(
                "select url, userName, engineType, systemKey, protected "
                "from alist_list where systemKey='taosync'"
            ).fetchall()
            mount_count = connection.execute(
                "select count(*) from storage_mount"
            ).fetchone()[0]
        self.assertEqual(
            rows,
            [("taosync://internal", "TaoSync", "taosync", "taosync", 1)],
        )
        self.assertEqual(mount_count, 0)

    def test_fresh_database_has_one_builtin_engine_and_init_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fresh.db"

            self._initialize(database)
            self._initialize(database)

            self._assert_builtin_engine(database)

    def test_legacy_database_migrates_builtin_engine_and_empty_mount_table(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "legacy.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript(
                    """
                    create table user_list(
                        id integer primary key autoincrement,
                        userName text,
                        passwd text,
                        sqlVersion integer,
                        createTime integer
                    );
                    insert into user_list(userName, passwd, sqlVersion)
                    values ('admin', 'hash', 260715);
                    create table alist_list(
                        id integer primary key autoincrement,
                        remark text,
                        url text,
                        userName text,
                        token text,
                        createTime integer default (strftime('%s', 'now')),
                        unique (url, userName)
                    );
                    insert into alist_list(remark, url, userName, token)
                    values ('existing', 'http://alist.test', 'admin', 'token');
                    """
                )

            self._initialize(database)
            self._initialize(database)

            self._assert_builtin_engine(database)
            with closing(sqlite3.connect(database)) as connection:
                external_count = connection.execute(
                    "select count(*) from alist_list where url='http://alist.test'"
                ).fetchone()[0]
                version = connection.execute(
                    "select sqlVersion from user_list limit 1"
                ).fetchone()[0]
            self.assertEqual(external_count, 1)
            self.assertEqual(version, 260718)

    def test_empty_user_table_with_business_data_is_not_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "damaged.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.executescript(
                    """
                    create table user_list(id integer primary key, userName text, passwd text, sqlVersion integer);
                    create table alist_list(id integer primary key, remark text, url text, userName text, token text);
                    insert into alist_list(id, url, userName) values (9, 'http://keep', 'admin');
                    """
                )
            with self.assertRaisesRegex(Exception, "refusing destructive recovery"):
                self._initialize(database)
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(
                    connection.execute("select count(*) from alist_list").fetchone()[0],
                    1,
                )


class LocalDriverTests(unittest.TestCase):
    def test_path_isolation_and_file_operations(self):
        with tempfile.TemporaryDirectory() as directory:
            driver = LocalDriver({"root_path": directory})
            payload = b"TaoSync local driver payload\x00\xff"

            with self.assertRaises(ValueError):
                driver.list("/../outside")
            with self.assertRaises(ValueError):
                driver.list("..\\outside")
            with self.assertRaises(ValueError):
                driver.delete("/")
            if os.name == "nt":
                with self.assertRaises(ValueError):
                    driver.upload("/bad:name", io.BytesIO(b"x"), size=1)
                with self.assertRaises(ValueError):
                    driver.upload("/CON.txt", io.BytesIO(b"x"), size=1)

            driver.mkdir("/nested/child")
            driver.upload(
                "/nested/child/payload.bin",
                io.BytesIO(payload),
                size=len(payload),
            )

            root_entries = driver.list("/")
            child_entries = driver.list("/nested/child")
            self.assertEqual(
                root_entries,
                [{"name": "nested", "is_dir": True, "size": None}],
            )
            self.assertEqual(
                child_entries,
                [{"name": "payload.bin", "is_dir": False, "size": len(payload)}],
            )

            downloaded = io.BytesIO()
            driver.download("/nested/child/payload.bin", downloaded)
            self.assertEqual(downloaded.getvalue(), payload)

            driver.delete("/nested/child/payload.bin")
            self.assertEqual(driver.list("/nested/child"), [])
            driver.delete("/nested")
            self.assertFalse(os.path.exists(Path(directory) / "nested"))


class TaoSyncClientTests(unittest.TestCase):
    def test_async_copy_between_local_mounts_then_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory) / "source"
            destination_root = Path(directory) / "destination"
            source_root.mkdir()
            destination_root.mkdir()
            payload = b"cross-mount transfer\n" * 4096
            (source_root / "payload.bin").write_bytes(payload)
            mounts = [
                {
                    "id": 11,
                    "engineId": 1,
                    "name": "source",
                    "driverType": "local",
                    "config": {"root_path": str(source_root)},
                    "enabled": 1,
                },
                {
                    "id": 12,
                    "engineId": 1,
                    "name": "destination",
                    "driverType": "local",
                    "config": {"root_path": str(destination_root)},
                    "enabled": 1,
                },
            ]

            with patch(
                "service.engine.taosyncClient.storageMapper.getMountList",
                return_value=mounts,
            ):
                client = TaoSyncClient(1)

            task_id = client.copyFile("/source", "/destination", "payload.bin")
            deadline = time.monotonic() + 5
            info = client.taskInfo(task_id)
            while info["state"] not in (2, 4, 7) and time.monotonic() < deadline:
                time.sleep(0.01)
                info = client.taskInfo(task_id)

            self.assertEqual(info["state"], 2, info)
            self.assertEqual(info["progress"], 100.0)
            self.assertEqual((destination_root / "payload.bin").read_bytes(), payload)
            self.assertIn(task_id, [task["id"] for task in client.copyTaskDone()])

            client.deleteFile("/destination", ["payload.bin"])
            client.deleteFile("/destination", ["payload.bin"])
            self.assertFalse((destination_root / "payload.bin").exists())
            self.assertTrue((source_root / "payload.bin").exists())

    def test_bad_mount_does_not_hide_healthy_mount(self):
        with tempfile.TemporaryDirectory() as directory:
            healthy_root = Path(directory) / "healthy"
            healthy_root.mkdir()
            mounts = [
                {
                    "id": 21,
                    "engineId": 1,
                    "name": "broken",
                    "driverType": "local",
                    "config": {"root_path": str(Path(directory) / "missing")},
                    "enabled": 1,
                },
                {
                    "id": 22,
                    "engineId": 1,
                    "name": "healthy",
                    "driverType": "local",
                    "config": {"root_path": str(healthy_root)},
                    "enabled": 1,
                },
            ]
            with patch(
                "service.engine.taosyncClient.storageMapper.getMountList",
                return_value=mounts,
            ):
                client = TaoSyncClient(1)
            self.assertEqual(
                list(client.fileListApi("/")),
                ["broken/", "healthy/"],
            )
            self.assertEqual(client.fileListApi("/healthy"), {})
            with self.assertRaisesRegex(RuntimeError, "broken"):
                client.fileListApi("/broken")

    def test_use_cache_reuses_entries_until_a_write_invalidates_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            root.mkdir()
            mounts = [
                {
                    "id": 31,
                    "engineId": 1,
                    "name": "cache",
                    "driverType": "local",
                    "config": {"root_path": str(root)},
                    "enabled": 1,
                }
            ]
            with patch(
                "service.engine.taosyncClient.storageMapper.getMountList",
                return_value=mounts,
            ):
                client = TaoSyncClient(1)
            driver = client.mounts["cache"]["driver"]
            with patch.object(driver, "list", wraps=driver.list) as listed:
                client.fileListApi("/cache", useCache=1)
                client.fileListApi("/cache", useCache=1)
                self.assertEqual(listed.call_count, 1)
                client.mkdir("/cache/new")
                client.fileListApi("/cache", useCache=1)
                self.assertEqual(listed.call_count, 2)

    def test_exclude_paths_are_relative_to_the_engine_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "root"
            (root / "sub").mkdir(parents=True)
            (root / "sub" / "skip.txt").write_text("skip", encoding="utf-8")
            mounts = [
                {
                    "id": 32,
                    "engineId": 1,
                    "name": "cache",
                    "driverType": "local",
                    "config": {"root_path": str(root)},
                    "enabled": 1,
                }
            ]
            with patch(
                "service.engine.taosyncClient.storageMapper.getMountList",
                return_value=mounts,
            ):
                client = TaoSyncClient(1)

            class Spec:
                def match_file(self, path):
                    return path == "sub/skip.txt"

            result = client.fileListApi(
                "/cache/sub/", spec=Spec(), rootPath="/cache/"
            )
            self.assertEqual(result, {})


class StorageServiceTests(unittest.TestCase):
    def test_account_switch_drops_derived_aliyun_tokens(self):
        old = {
            "id": 41,
            "engineId": 1,
            "name": "cloud",
            "driverType": "aliyun",
            "config": {
                "client_id": "old-client",
                "client_secret": "old-secret",
                "refresh_token": "old-refresh",
                "access_token": "old-access",
                "expires_at": 9999999999,
                "drive_id": "old-drive",
                "drive_type": "resource",
            },
            "enabled": 1,
            "authVersion": 3,
        }
        captured = {}
        with patch.object(storageService.storageMapper, "getMountById", return_value=old), patch.object(
            storageService, "_requireTaoSync"
        ), patch.object(storageService, "_normalizeDriverConfig", side_effect=lambda _t, config: config), patch.object(
            storageService.storageMapper, "updateMount", side_effect=lambda row: captured.update(row)
        ), patch.object(storageService, "_invalidateEngine"):
            storageService.updateMount(
                {
                    "id": 41,
                    "name": "cloud",
                    "driverType": "aliyun",
                    "config": {
                        "client_id": "new-client",
                        "client_secret": "new-secret",
                        "refresh_token": "new-refresh",
                        "drive_type": "backup",
                    },
                }
            )
        self.assertNotIn("access_token", captured["config"])
        self.assertNotIn("expires_at", captured["config"])
        self.assertNotIn("drive_id", captured["config"])
        self.assertEqual(captured["authVersion"], 4)


class TransferPipeTests(unittest.TestCase):
    class _Source:
        def __init__(self, error=None):
            self.error = error

        def download(self, path, target, progress=None, cancel=None):
            target.write(b"payload")
            if self.error:
                raise self.error

    class _Destination:
        def __init__(self, error=None, cancel_on_read=False):
            self.error = error
            self.cancel_on_read = cancel_on_read

        def upload(self, path, source, size, progress=None, cancel=None):
            source.read()
            if self.cancel_on_read:
                while cancel is not None and not cancel.is_set():
                    time.sleep(0.001)
                raise TransferCancelled("internal stop")
            if self.error:
                raise self.error

    def test_destination_failure_is_not_masked_by_internal_source_cancel(self):
        with self.assertRaisesRegex(OSError, "destination failed"):
            stream_transfer(
                self._Source(),
                "/source",
                self._Destination(OSError("destination failed")),
                "/destination",
                7,
            )

    def test_external_cancel_wins_over_destination_length_failure(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(TransferCancelled):
            stream_transfer(
                self._Source(),
                "/source",
                self._Destination(OSError("length mismatch")),
                "/destination",
                7,
                cancel=cancel,
            )

    def test_source_failure_is_not_masked_by_internal_destination_cancel(self):
        with self.assertRaisesRegex(OSError, "source failed"):
            stream_transfer(
                self._Source(OSError("source failed")),
                "/source",
                self._Destination(cancel_on_read=True),
                "/destination",
                7,
            )


class AliyunDriveDriverTests(unittest.TestCase):
    def _session(self):
        return MagicMock(name="aliyun-session")

    def test_expired_token_is_refreshed_and_list_items_are_mapped(self):
        session = self._session()
        session.post.return_value = _Response(
            data={
                "access_token": "new-access-token",
                "refresh_token": "rotated-refresh-token",
                "expires_in": 3600,
            }
        )
        session.request.return_value = _Response(
            data={
                "items": [
                    {"file_id": "file-1", "name": "z.txt", "type": "file", "size": "7"},
                    {"file_id": "folder-1", "name": "A", "type": "folder"},
                ],
                "next_marker": "",
            }
        )
        persisted = []
        config = {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "refresh_token": "old-refresh-token",
            "drive_id": "drive-1",
        }

        with patch(
            "service.storage.drivers.aliyun.requests.Session", return_value=session
        ):
            driver = AliyunDriveDriver(config, save_config=persisted.append)
            entries = driver.list("/")
            detailedEntries = driver.list("/", details=True)

        self.assertEqual(
            entries,
            [
                {"name": "A", "is_dir": True, "size": None},
                {"name": "z.txt", "is_dir": False, "size": 7},
            ],
        )
        self.assertTrue(
            all(item["fingerprint"].startswith("aliyun:sha256:")
                for item in detailedEntries)
        )
        session.post.assert_called_once()
        oauth_payload = session.post.call_args.kwargs["json"]
        self.assertEqual(oauth_payload["grant_type"], "refresh_token")
        self.assertEqual(oauth_payload["refresh_token"], "old-refresh-token")
        request_headers = session.request.call_args.kwargs["headers"]
        self.assertEqual(request_headers["Authorization"], "Bearer new-access-token")
        self.assertEqual(persisted[-1]["refresh_token"], "rotated-refresh-token")

    def test_upload_creates_parts_uploads_bytes_and_completes(self):
        session = self._session()
        uploaded = bytearray()

        def api_request(method, url, json=None, **kwargs):
            if url.endswith("/adrive/v1.0/openFile/create"):
                return _Response(
                    data={
                        "file_id": "file-new",
                        "upload_id": "upload-1",
                        "part_info_list": [
                            {"part_number": 1, "upload_url": "https://upload.test/part-1"}
                        ],
                    }
                )
            if url.endswith("/adrive/v1.0/openFile/complete"):
                return _Response(data={"file_id": "file-new"})
            if url.endswith("/adrive/v1.0/openFile/list"):
                return _Response(
                    data={
                        "items": [
                            {
                                "file_id": "file-new",
                                "name": "payload.bin",
                                "type": "file",
                                "size": 7,
                            }
                        ],
                        "next_marker": "",
                    }
                )
            raise AssertionError("unexpected Aliyun endpoint: " + url)

        def upload_part(url, data=None, **kwargs):
            self.assertEqual(url, "https://upload.test/part-1")
            while True:
                chunk = data.read(3)
                if not chunk:
                    break
                uploaded.extend(chunk)
            return _Response(status_code=200)

        session.request.side_effect = api_request
        session.put.side_effect = upload_part
        config = {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "refresh_token": "refresh-token",
            "access_token": "valid-access-token",
            "expires_at": time.time() + 3600,
            "drive_id": "drive-1",
        }
        payload = b"1234567"

        with patch(
            "service.storage.drivers.aliyun.requests.Session", return_value=session
        ):
            driver = AliyunDriveDriver(config)
            progress = []
            driver.upload(
                "/payload.bin",
                io.BytesIO(payload),
                size=len(payload),
                progress=progress.append,
            )

        self.assertEqual(bytes(uploaded), payload)
        self.assertEqual(progress[-1], 1.0)
        endpoints = [call.args[1] for call in session.request.call_args_list]
        self.assertEqual(
            endpoints,
            [
                "https://openapi.alipan.com/adrive/v1.0/openFile/list",
                "https://openapi.alipan.com/adrive/v1.0/openFile/create",
                "https://openapi.alipan.com/adrive/v1.0/openFile/complete",
                "https://openapi.alipan.com/adrive/v1.0/openFile/list",
            ],
        )
        create_payload = session.request.call_args_list[1].kwargs["json"]
        complete_payload = session.request.call_args_list[2].kwargs["json"]
        self.assertEqual(create_payload["name"], "payload.bin")
        self.assertEqual(create_payload["part_info_list"], [{"part_number": 1}])
        self.assertEqual(complete_payload["upload_id"], "upload-1")
        session.post.assert_not_called()

    def test_duplicate_cleanup_never_deletes_a_same_named_folder(self):
        session = self._session()
        config = {
            "client_id": "client-id",
            "client_secret": "client-secret",
            "refresh_token": "refresh-token",
            "access_token": "valid-access-token",
            "expires_at": time.time() + 3600,
            "drive_id": "drive-1",
        }
        with patch(
            "service.storage.drivers.aliyun.requests.Session", return_value=session
        ):
            driver = AliyunDriveDriver(config)
        entries = [
            {"file_id": "folder-1", "name": "same", "type": "folder"},
            {"file_id": "file-new", "name": "same", "type": "file"},
        ]
        with patch.object(driver, "_list_id", return_value=entries), patch.object(
            driver, "_abort_upload"
        ) as abort, patch.object(driver, "_delete_id") as delete:
            with self.assertRaises(IsADirectoryError):
                driver._remove_duplicates("root", "same", "file-new")
        abort.assert_called_once_with("file-new")
        delete.assert_not_called()


class FtpDriverSafetyTests(unittest.TestCase):
    def test_mlsd_metadata_produces_an_opaque_fingerprint_on_request(self):
        ftp = MagicMock()
        ftp.mlsd.return_value = [
            (
                "payload.bin",
                {
                    "type": "file",
                    "size": "4",
                    "unique": "raw-unique-id",
                    "modify": "20260717010203",
                },
            )
        ]
        driver = FtpDriver.__new__(FtpDriver)

        entries = driver._entries(ftp, "/", details=True)

        self.assertTrue(entries[0]["fingerprint"].startswith("ftp:sha256:"))
        self.assertNotIn("raw-unique-id", entries[0]["fingerprint"])

    def test_replace_refuses_to_rename_an_existing_directory(self):
        ftp = MagicMock()
        ftp.mlsd.return_value = [("destination", {"type": "dir"})]
        with self.assertRaises(IsADirectoryError):
            FtpDriver._replace_file(ftp, "/temporary", "/destination")
        ftp.rename.assert_not_called()


if __name__ == "__main__":
    unittest.main()
