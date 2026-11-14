import os
import tempfile
import unittest
from unittest import mock

from service.engine.taosyncClient import TaoSyncClient
from service.storage import storageService
from service.storage.pathIdentity import mount_paths_overlap
from service.syncJob import jobClient, jobService


def mount(name, driver_type, config):
    return {
        "id": len(name),
        "name": name,
        "driverType": driver_type,
        "config": config,
        "enabled": 1,
    }


class StoragePathIdentityTest(unittest.TestCase):
    def test_local_mount_aliases_use_canonical_physical_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = os.path.join(temp, "root")
            nested = os.path.join(root, "nested")
            sibling = os.path.join(temp, "sibling")
            os.makedirs(nested)
            os.makedirs(sibling)
            mounts = [
                mount("A", "local", {"root_path": root}),
                mount("B", "local", {"root_path": nested}),
                mount("C", "local", {"root_path": sibling}),
            ]

            self.assertTrue(mount_paths_overlap(mounts, "/A/nested/data", "/B/data"))
            self.assertFalse(mount_paths_overlap(mounts, "/A/data", "/C/data"))
            case_alias = mount_paths_overlap(
                mounts, "/A/CaseSensitive", "/A/casesensitive/child"
            )
            self.assertEqual(
                case_alias,
                os.path.normcase("CaseSensitive") == os.path.normcase("casesensitive"),
            )

    def test_smb_aliases_are_case_insensitive_and_endpoint_scoped(self):
        mounts = [
            mount("A", "smb", {
                "host": "NAS.EXAMPLE.", "port": 445, "share": "Media",
                "root_path": "Library",
            }),
            mount("B", "smb", {
                "host": "nas.example", "port": 445, "share": "media",
                "root_path": "library\\Movies",
            }),
            mount("C", "smb", {
                "host": "nas.example", "port": 445, "share": "archive",
                "root_path": "library",
            }),
        ]

        self.assertTrue(mount_paths_overlap(mounts, "/A/MOVIES/item", "/B/item"))
        self.assertFalse(mount_paths_overlap(mounts, "/A/MOVIES/item", "/C/item"))

    def test_ftp_and_sftp_use_separate_case_sensitive_backend_identities(self):
        mounts = [
            mount("F1", "ftp", {
                "host": "FILES.EXAMPLE.", "port": 21, "username": "user",
                "root_path": "/Data",
            }),
            mount("F2", "ftp", {
                "host": "files.example", "port": 21, "username": "user",
                "root_path": "/Data/Inbox",
            }),
            mount("F3", "ftp", {
                "host": "files.example", "port": 21, "username": "other",
                "root_path": "/Data/Inbox",
            }),
            mount("S1", "sftp", {
                "host": "files.example", "port": 21, "username": "user",
                "root_path": "/Data/Inbox",
            }),
        ]

        self.assertTrue(mount_paths_overlap(mounts, "/F1/Inbox/item", "/F2/item"))
        self.assertFalse(mount_paths_overlap(mounts, "/F1/inbox/item", "/F2/item"))
        self.assertFalse(mount_paths_overlap(mounts, "/F1/Inbox/item", "/F3/item"))
        self.assertFalse(mount_paths_overlap(mounts, "/F1/Inbox/item", "/S1/item"))

    def test_aliyun_conservatively_blocks_two_roots_on_the_same_drive(self):
        mounts = [
            mount("A", "aliyun", {
                "api_url": "https://openapi.alipan.com/", "client_id": "app",
                "refresh_token": "account-a", "drive_id": "drive-1",
                "root_folder_id": "root-a",
            }),
            mount("B", "aliyun", {
                "api_url": "https://OPENAPI.ALIPAN.COM", "client_id": "app",
                "refresh_token": "rotated-account-a", "drive_id": "drive-1",
                "root_folder_id": "root-b",
            }),
            mount("C", "aliyun", {
                "api_url": "https://openapi.alipan.com", "client_id": "app",
                "refresh_token": "account-c", "drive_id": "drive-2",
                "root_folder_id": "root-a",
            }),
        ]

        self.assertTrue(mount_paths_overlap(mounts, "/A/data", "/B/data"))
        self.assertFalse(mount_paths_overlap(mounts, "/A/data", "/C/data"))

    def test_taosync_client_allows_case_distinct_sftp_paths(self):
        client = TaoSyncClient.__new__(TaoSyncClient)
        client.mounts = {
            "S": mount("S", "sftp", {
                "host": "files.example", "port": 22, "username": "user",
                "root_path": "/",
            })
        }

        self.assertFalse(client.pathsOverlap("/S/Data", "/S/data"))


class StoragePathJobGuardTest(unittest.TestCase):
    @staticmethod
    def job():
        return {
            "enable": 1,
            "isCron": 2,
            "alistId": 1,
            "srcPath": "/A/data/",
            "dstPath": "/B/data/",
            "method": 2,
            "exclude": None,
            "minFileSize": None,
            "maxFileSize": None,
            "sourceMode": 1,
        }

    @staticmethod
    def alias_mounts():
        return [
            mount("A", "smb", {
                "host": "nas", "share": "data", "root_path": "root",
            }),
            mount("B", "smb", {
                "host": "NAS", "share": "DATA", "root_path": "ROOT",
            }),
        ]

    def test_job_input_rejects_backend_mount_aliases(self):
        engine = {"id": 1, "engineType": "taosync", "systemKey": "taosync"}
        with mock.patch.object(storageService, "getEngineById", return_value=engine), \
                mock.patch.object(
                    storageService.storageMapper, "getMountList", return_value=self.alias_mounts()
                ):
            with self.assertRaises(Exception):
                jobService.cleanJobInput(self.job())

    def test_job_input_allows_unrelated_backends(self):
        engine = {"id": 1, "engineType": "taosync", "systemKey": "taosync"}
        mounts = [
            mount("A", "smb", {
                "host": "nas-a", "share": "data", "root_path": "root",
            }),
            mount("B", "smb", {
                "host": "nas-b", "share": "data", "root_path": "root",
            }),
        ]
        value = self.job()
        with mock.patch.object(storageService, "getEngineById", return_value=engine), \
                mock.patch.object(
                    storageService.storageMapper, "getMountList", return_value=mounts
                ):
            jobService.cleanJobInput(value)

        self.assertEqual(value["sourceMode"], 1)

    def test_job_runtime_rejects_aliases_from_loaded_client(self):
        class AliasAwareEngine:
            def __init__(inner_self):
                inner_self.listCalls = []

            def pathsOverlap(inner_self, first, second):
                return True

            def fileListApi(inner_self, path, *args, **kwargs):
                inner_self.listCalls.append(path)
                return {}

        engine = AliasAwareEngine()
        task = jobClient.JobTask.__new__(jobClient.JobTask)
        task.taskId = 9
        task.job = self.job()
        task.alistClient = engine
        task.finish = []
        task.breakFlag = False
        task.sourceScanFailed = False
        task.scanFinish = False

        with mock.patch.object(jobClient.jobMapper, "getSourceSnapshot") as get_snapshot:
            task.sync()

        self.assertTrue(task.scanFinish)
        self.assertTrue(task.sourceScanFailed)
        self.assertEqual(engine.listCalls, [])
        get_snapshot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
