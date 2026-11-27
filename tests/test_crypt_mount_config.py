"""Crypt mount configuration through the service and a disposable SQLite database."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from common import config, sqlBase, sqlInit
from mapper import storageMapper as mapper
from service.engine import engineService
from service.storage import mountConfig, storageService as storage


class CryptMountConfigTests(unittest.TestCase):
    passphrase = "  synthetic test passphrase 密  "

    def setUp(self):
        temp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = temp / "backing"
        self.vault = self.root / "dir" / "vault"
        self.vault.mkdir(parents=True)
        self.enterContext(patch.object(config, "sysConfig", {
            "db": {"dbname": str(temp / "mounts.db")},
            "server": {"password": "fixture", "passwdStr": "synthetic install secret"},
        }))
        self.enterContext(patch.multiple(engineService, clientList={}, engineLocks={}, copyLimiters={}))
        sqlInit.init_sql()
        self.engine = sqlBase.fetch_first_val("select id from alist_list where systemKey='taosync'")
        self.base = self.add("base", "local", {"root_path": str(self.root)})

    def add(self, name, driver, settings):
        return storage.addMount({"engineId": self.engine, "name": name, "driverType": driver, "config": settings})

    def crypt(self, name="vault", **overrides):
        return self.add(name, "crypt", {"target_mount_id": self.base, "target_path": "dir/vault/",
                                        "encryption_key": self.passphrase, **overrides})

    def test_saved_and_public_configs_and_runtime_key(self):
        mount = self.crypt(encrypt_dir_names=True)
        stored = mapper.getMountById(mount)["config"]
        self.assertEqual(set(stored), mountConfig.CRYPT_FIELDS)
        self.assertEqual(stored["target_path"], "/dir/vault")
        self.assertIs(stored["encrypt_dir_names"], True)
        self.assertEqual(mountConfig.getMountEncryptionKey(stored), self.passphrase)
        self.assertNotIn(self.passphrase, sqlBase.fetch_first_val("select config from storage_mount where id=?", (mount,)))
        with patch.object(mountConfig, "_keyCipher", side_effect=AssertionError("unexpected key access")):
            rows = {row["id"]: row for row in storage.getMountList(self.engine)}
            public = rows[mount]
            self.assertEqual(public["config"]["encryption_key"], "")
            self.assertTrue(public["secretState"]["encryption_key"])
            self.assertNotIn(stored["encryption_key"], json.dumps(public))
            self.assertEqual(rows[self.base]["config"], {"root_path": str(self.root)})
            storage.updateMount({"id": mount, "config": public["config"], "copyConcurrency": 9})
            storage.updateMount({"id": mount, "config": {}})
        self.assertEqual(mapper.getMountById(mount)["config"], stored)
        self.assertEqual(list(self.vault.iterdir()), [])

    def test_clear_or_unreadable_keys_fail_closed_with_redacted_errors(self):
        stored = mapper.getMountById(self.crypt())["config"]
        with patch.object(config, "sysConfig", {"server": {"passwdStr": "different synthetic secret"}}):
            for key in (self.passphrase, stored["encryption_key"], "fernet:v1:bad", None):
                with self.assertRaisesRegex(ValueError, "cannot open") as failure:
                    mountConfig.getMountEncryptionKey({"encryption_key": key})
                self.assertNotIn(str(key), str(failure.exception))

    def test_reject_invalid_or_misplaced_settings(self):
        bad = {"target_mount_id": [True, 0, -1, 1.5, "1", 2**63],
               "target_path": [None, "", "../escape", "/a/../b", "//server/share", "D:/data", "a\\b", "a\0b"],
               "encryption_key": [None, False, "", "  "], "encrypt_dir_names": [1, "false", None],
               "encrypt_backup": [True], "host": ["invalid"]}
        with patch.object(engineService, "getClientById", side_effect=AssertionError("unexpected directory lookup")):
            for field, values in bad.items():
                for value in values:
                    with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                        self.crypt(**{field: value})
        for field in [*mountConfig.CRYPT_FIELDS, "encrypt_backup"]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                storage.updateMount({"id": self.base, "config": {field: self.passphrase}})
        with self.assertRaises(ValueError):
            self.add("ordinary", "local", {"root_path": str(self.root), "encryption_key": self.passphrase})
        self.assertEqual(len(mapper.getMountList(self.engine)), 1)

    def test_target_must_be_an_enabled_regular_mount_of_this_engine(self):
        crypt_id = self.crypt(target_path="/")
        other = mapper.addMount({"engineId": self.engine + 100, "name": "foreign", "driverType": "local", "config": {}})
        disabled = mapper.addMount({"engineId": self.engine, "name": "disabled", "driverType": "local", "config": {}, "enabled": 0})
        for target in (other, disabled, crypt_id, 987654321):
            with self.subTest(target=target), patch.object(engineService, "getClientById") as client, self.assertRaises(ValueError):
                try:
                    self.crypt("invalid", target_mount_id=target)
                finally:
                    client.assert_not_called()

    def test_target_probe_ignores_cached_directories_and_cannot_create_paths(self):
        (self.root / "ordinary-file").write_text("fixture", encoding="utf8")
        client = engineService.getClientById(self.engine)
        client._entries("/base/dir")
        client._entries("/base/dir/vault")
        self.vault.rmdir()
        for path in ("/dir/vault", "/ordinary-file", "/missing"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "directory"):
                self.crypt(target_path=path)
        self.assertFalse(self.vault.exists())
        self.assertFalse((self.root / "missing").exists())
        self.assertEqual(len(mapper.getMountList(self.engine)), 1)

    def test_saved_crypt_settings_and_target_are_immutable(self):
        mount = self.crypt()
        stored = mapper.getMountById(mount)
        for delta in ({"target_mount_id": self.base + 5}, {"target_path": "/"}, {"encrypt_dir_names": True},
                      {"encryption_key": self.passphrase}, {"encryption_key": stored["config"]["encryption_key"]}):
            with self.subTest(field=next(iter(delta))), self.assertRaises(ValueError):
                storage.updateMount({"id": mount, "config": delta})
        self.assertEqual(mapper.getMountById(mount), stored)
        self.assertIsNone(storage.updateMountConfig(mount, 1, {"drive_id": "unrelated"}))
        storage.updateMount({"id": mount, "copyConcurrency": 8})
        current = mapper.getMountById(mount)
        self.assertEqual(current["copyConcurrency"], 8)
        self.assertEqual(current["configVersion"], stored["configVersion"])

    def test_disabled_references_still_guard_backing_mount(self):
        first = self.crypt("first")
        second = self.crypt("second")
        storage.updateMount({"id": second, "enabled": 0})
        storage.removeMount(first)
        for data in ({"enabled": 0}, {"config": {"root_path": str(self.vault)}}):
            with self.assertRaisesRegex(ValueError, "referenced"):
                storage.updateMount({"id": self.base, **data})
        with self.assertRaisesRegex(ValueError, "referencing"):
            storage.removeMount(self.base)
        storage.removeMount(second)
        storage.updateMount({"id": self.base, "config": {"root_path": str(self.vault)}})
        storage.removeMount(self.base)
        self.assertEqual(mapper.getMountList(self.engine), [])

    def test_race_when_target_moves_or_disappears_after_probe(self):
        insert = mapper.addMount
        def move_before_insert(mount, target):
            storage.updateMount({"id": self.base, "config": {"root_path": str(self.vault)}})
            return insert(mount, target=target)
        with patch.object(mapper, "addMount", side_effect=move_before_insert), self.assertRaisesRegex(ValueError, "changed"):
            self.crypt()
        def delete_before_insert(mount, target):
            storage.removeMount(self.base)
            return insert(mount, target=target)
        with patch.object(mapper, "addMount", side_effect=delete_before_insert), self.assertRaisesRegex(ValueError, "changed"):
            self.crypt(target_path="/")
        self.assertEqual(mapper.getMountList(self.engine), [])

    def test_race_when_reference_is_added_after_base_edit_is_prepared(self):
        update = mapper.updateMount
        def add_before_update(row):
            self.crypt()
            update(row)
        with patch.object(mapper, "updateMount", side_effect=add_before_update), self.assertRaisesRegex(ValueError, "referenced"):
            storage.updateMount({"id": self.base, "config": {"root_path": str(self.vault)}})
        self.assertEqual(mapper.getMountById(self.base)["config"]["root_path"], str(self.root))

    def test_referenced_aliyun_preserves_drive_and_accepts_background_rotation(self):
        cloud = self.add("cloud", "aliyun", {"client_id": "fixture", "refresh_token": "synthetic-token",
                                              "client_secret": "synthetic-client", "drive_type": "backup"})
        target = mapper.getMountById(cloud)
        client = Mock()
        client.resolve.return_value = target, "/"
        driver = client.getDriver.return_value
        driver.drive_id = "discovered-drive"
        driver.list.side_effect = lambda path: storage.updateMountConfig(cloud, 1, {"drive_id": driver.drive_id}) or []
        with patch.object(engineService, "getClientById", return_value=client):
            self.crypt(target_mount_id=cloud, target_path="/")
        for delta in ({"drive_type": "resource"}, {"drive_id": "other"}, {"root_folder_id": "other"},
                      {"access_token": "other"}, {"refresh_token": "other"}):
            with self.subTest(field=next(iter(delta))), self.assertRaisesRegex(ValueError, "referenced"):
                storage.updateMount({"id": cloud, "config": delta})
        self.assertTrue(storage.updateMountConfig(cloud, 1, {"refresh_token": "rotated"}))
        self.assertTrue(storage.updateMountConfig(cloud, 1, {"drive_id": "other"})["conflict"])
        epoch = mapper.getMountById(cloud)['cacheEpoch']
        with patch('mapper.jobMapper.clearSourceSnapshotsByEngine') as clear_snapshots:
            storage.updateMount({"id": cloud, "config": {"rapid_upload_min_mb": 32}})
            threshold = {'value': 512, 'unit': 'KB'}
            storage.updateMount({"id": cloud, "config": {"rapid_upload_threshold": threshold}})
            storage.updateMount({"id": cloud, "config": {"rapid_upload": False}})
        clear_snapshots.assert_not_called()
        self.assertEqual(mapper.getMountById(cloud)['cacheEpoch'], epoch)
        cloud_config = mapper.getMountById(cloud)["config"]
        self.assertEqual(cloud_config['rapid_upload_threshold'], threshold)
        self.assertNotIn('rapid_upload_min_mb', cloud_config)
        self.assertEqual(cloud_config["drive_id"], driver.drive_id)
        self.assertEqual(cloud_config["refresh_token"], "rotated")
        self.assertFalse(cloud_config["rapid_upload"])
        storage.updateMount({"id": cloud, "config": {"rapid_upload_min_mb": 0}})
        legacy_config = mapper.getMountById(cloud)['config']
        self.assertEqual(legacy_config['rapid_upload_min_mb'], 0)
        self.assertNotIn('rapid_upload_threshold', legacy_config)

    def test_configuration_browsers_cannot_receive_crypt_keys(self):
        mount = self.crypt()
        for browse in (storage.testSftp, storage.browseSftp, storage.discoverSmbShares, storage.browseAliyun):
            for request in ({"mountId": mount}, {"config": {"encryption_key": self.passphrase}}):
                with self.subTest(browse=browse.__name__), patch.object(storage, "createDriver") as create, \
                        patch.object(storage.discoveryService, "list_smb_shares") as discover:
                    with self.assertRaises(ValueError) as failure:
                        browse({"engineId": self.engine, "path": "/", **request})
                    create.assert_not_called()
                    discover.assert_not_called()
                    self.assertNotIn(self.passphrase, str(failure.exception))

    def test_network_target_rejects_location_edits_but_allows_password_change(self):
        fixtures = {
            "smb": ({"server": "fixture", "share": "volume"}, {"share": "other"}),
            "sftp": ({"host": "fixture"}, {"username": "other"}),
            "ftp": ({"host": "fixture"}, {"port": 2100}),
        }
        for kind, (settings, delta) in fixtures.items():
            with self.subTest(driver=kind):
                base = self.add(kind, kind, {**settings, "username": "user", "password": "fixture"})
                client = Mock()
                client.resolve.return_value = mapper.getMountById(base), "/"
                client.getDriver.return_value.list.return_value = []
                with patch.object(engineService, "getClientById", return_value=client):
                    self.crypt(kind + "-vault", target_mount_id=base, target_path="/")
                for move in (delta, {"root_path": "/other"}, {"host": "other"}):
                    with self.assertRaisesRegex(ValueError, "referenced"):
                        storage.updateMount({"id": base, "config": {**move, "password": "other"}})
                storage.updateMount({"id": base, "config": {"password": "replaced"}})
                self.assertEqual(mapper.getMountById(base)["config"]["password"], "replaced")

    def test_stale_edits_cannot_revert_concurrency_or_rotated_tokens(self):
        cloud = self.add("cloud", "aliyun", {"client_id": "fixture", "client_secret": "synthetic-client",
                                              "refresh_token": "synthetic-token"})
        update = mapper.updateMount
        def rotate_before_update(row):
            storage.updateMountConfig(cloud, 1, {"refresh_token": "rotated"})
            update(row)
        with patch.object(mapper, "updateMount", side_effect=rotate_before_update), self.assertRaisesRegex(ValueError, "changed"):
            storage.updateMount({"id": cloud, "config": {"rapid_upload": False}})
        self.assertEqual(mapper.getMountById(cloud)["config"]["refresh_token"], "rotated")
        def change_limit_before_update(row):
            mapper.updateCopyConcurrency(cloud, 8)
            update(row)
        before = mapper.getMountById(cloud)["configVersion"]
        with patch.object(mapper, "updateMount", side_effect=change_limit_before_update), self.assertRaisesRegex(ValueError, "changed"):
            storage.updateMount({"id": cloud, "config": {"rapid_upload": False}})
        current = mapper.getMountById(cloud)
        self.assertEqual((current["configVersion"], current["copyConcurrency"]), (before, 8))
        # Cache retention edits through the full form must keep optimistic locking and preserve source snapshots.
        def bump_limit_before_update(row):
            mapper.updateCopyConcurrency(cloud, 9)
            update(row)
        with patch.object(mapper, "updateMount", side_effect=bump_limit_before_update), self.assertRaisesRegex(ValueError, "changed"):
            storage.updateMount({"id": cloud, "cacheDays": 7, "config": {}})
        with patch('mapper.jobMapper.clearSourceSnapshotsByEngine') as clear_snapshots:
            storage.updateMount({"id": cloud, "cacheDays": 7, "copyConcurrency": 9, "config": {}})
            storage.updateMount({"id": self.base, "copyConcurrency": 6, "config": {"root_path": str(self.root)}})
        clear_snapshots.assert_not_called()
        self.assertEqual(mapper.getMountById(cloud)["cacheDays"], 7)
        self.assertEqual(mapper.getMountById(self.base)["copyConcurrency"], 6)
