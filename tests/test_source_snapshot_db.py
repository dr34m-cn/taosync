import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from common.sqlInit import init_sql
from mapper import jobMapper


class SourceSnapshotDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database = Path(self.directory.name) / "snapshot.db"
        self.config = {
            "db": {"dbname": str(self.database)},
            "server": {"password": "test-password"},
        }
        self.sqlConfigPatch = patch(
            "common.sqlBase.getConfig", return_value=self.config
        )
        self.sqlConfigPatch.start()
        self.addCleanup(self.sqlConfigPatch.stop)
        self.addCleanup(self.directory.cleanup)
        self._initialize()

    def _initialize(self):
        with patch("common.sqlInit.getConfig", return_value=self.config):
            init_sql()

    def _job(self, sourceMode=0):
        return {
            "enable": 0,
            "remark": "snapshot test",
            "srcPath": "/source/",
            "dstPath": "/target/",
            "alistId": 1,
            "useCacheT": 0,
            "scanIntervalT": 0,
            "useCacheS": 0,
            "scanIntervalS": 0,
            "method": 0,
            "sourceMode": sourceMode,
            "interval": 60,
            "isCron": 2,
            "year": None,
            "month": None,
            "day": None,
            "week": None,
            "day_of_week": None,
            "hour": None,
            "minute": None,
            "second": None,
            "start_date": None,
            "end_date": None,
            "exclude": None,
            "minFileSize": None,
            "maxFileSize": None,
        }

    def test_fresh_schema_has_source_mode_and_snapshot_tables(self):
        with closing(sqlite3.connect(self.database)) as connection:
            jobColumns = {
                row[1] for row in connection.execute("pragma table_info(job)")
            }
            tables = {
                row[0] for row in connection.execute(
                    "select name from sqlite_master where type='table'"
                )
            }
            version = connection.execute(
                "select sqlVersion from user_list limit 1"
            ).fetchone()[0]

        self.assertIn("sourceMode", jobColumns)
        self.assertIn("job_source_snapshot_meta", tables)
        self.assertIn("job_source_snapshot", tables)
        self.assertEqual(version, 260718)
        with closing(sqlite3.connect(self.database)) as connection:
            snapshotColumns = {
                row[1] for row in connection.execute(
                    "pragma table_info(job_source_snapshot)"
                )
            }
        self.assertIn("fingerprint", snapshotColumns)

    def test_legacy_schema_migration_is_idempotent(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript(
                """
                drop table job_source_snapshot;
                drop table job_source_snapshot_meta;
                alter table job drop column sourceMode;
                update user_list set sqlVersion=260716;
                """
            )

        self._initialize()
        self._initialize()

        with closing(sqlite3.connect(self.database)) as connection:
            sourceModeCount = connection.execute(
                "select count(*) from pragma_table_info('job') where name='sourceMode'"
            ).fetchone()[0]
            version = connection.execute(
                "select sqlVersion from user_list limit 1"
            ).fetchone()[0]
            tableCount = connection.execute(
                "select count(*) from sqlite_master where type='table' "
                "and name in ('job_source_snapshot_meta', 'job_source_snapshot')"
            ).fetchone()[0]

        self.assertEqual(sourceModeCount, 1)
        self.assertEqual(tableCount, 2)
        self.assertEqual(version, 260718)

    def test_version_260717_snapshot_table_gains_fingerprint_column(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript(
                """
                alter table job_source_snapshot rename to old_job_source_snapshot;
                create table job_source_snapshot(
                    jobId integer not null,
                    path text not null,
                    isDir integer default 0,
                    size integer default null,
                    primary key (jobId, path)
                );
                insert into job_source_snapshot(jobId, path, isDir, size)
                    select jobId, path, isDir, size from old_job_source_snapshot;
                drop table old_job_source_snapshot;
                update user_list set sqlVersion=260717;
                """
            )

        self._initialize()
        self._initialize()

        with closing(sqlite3.connect(self.database)) as connection:
            columns = {
                row[1] for row in connection.execute(
                    "pragma table_info(job_source_snapshot)"
                )
            }
            version = connection.execute(
                "select sqlVersion from user_list limit 1"
            ).fetchone()[0]
        self.assertIn("fingerprint", columns)
        self.assertEqual(version, 260718)

    def test_interrupted_migration_repairs_missing_snapshot_table(self):
        with closing(sqlite3.connect(self.database)) as connection:
            connection.executescript(
                """
                drop table job_source_snapshot;
                update user_list set sqlVersion=260716;
                """
            )

        self._initialize()

        with closing(sqlite3.connect(self.database)) as connection:
            sourceModeCount = connection.execute(
                "select count(*) from pragma_table_info('job') where name='sourceMode'"
            ).fetchone()[0]
            snapshotTableCount = connection.execute(
                "select count(*) from sqlite_master where type='table' "
                "and name='job_source_snapshot'"
            ).fetchone()[0]

        self.assertEqual(sourceModeCount, 1)
        self.assertEqual(snapshotTableCount, 1)

    def test_job_mapper_persists_source_mode(self):
        job = self._job(sourceMode=1)
        jobId = jobMapper.addJob(job)
        self.assertEqual(jobMapper.getJobById(jobId)["sourceMode"], 1)

        job.update({"id": jobId, "sourceMode": 0})
        jobMapper.updateJob(job)

        self.assertEqual(jobMapper.getJobById(jobId)["sourceMode"], 0)

    def test_job_update_can_invalidate_snapshot_in_the_same_transaction(self):
        job = self._job(sourceMode=1)
        jobId = jobMapper.addJob(job)
        jobMapper.replaceSourceSnapshot(
            jobId, [{"path": "old.txt", "isDir": 0, "size": 1}]
        )
        job.update({"id": jobId, "srcPath": "/new-source/"})

        jobMapper.updateJob(job, clearSourceSnapshot=True)

        self.assertEqual(jobMapper.getJobById(jobId)["srcPath"], "/new-source/")
        self.assertEqual(
            jobMapper.getSourceSnapshot(jobId)["meta"]["initialized"], 0
        )

    def test_snapshot_round_trip_and_empty_snapshot_initialization(self):
        jobId = jobMapper.addJob(self._job())
        self.assertEqual(
            jobMapper.getSourceSnapshot(jobId),
            {
                "meta": {
                    "jobId": jobId,
                    "initialized": 0,
                    "scanTime": None,
                    "entryCount": 0,
                },
                "entries": [],
            },
        )

        meta = jobMapper.replaceSourceSnapshot(
            jobId,
            [
                {"path": "docs/", "isDir": 1, "size": 123},
                {
                    "path": "docs/readme.txt",
                    "isDir": 0,
                    "size": 42,
                    "fingerprint": "local:sha256:test",
                },
            ],
        )
        snapshot = jobMapper.getSourceSnapshot(jobId)

        self.assertEqual(meta["entryCount"], 2)
        self.assertEqual(snapshot["meta"], meta)
        self.assertEqual(
            snapshot["entries"],
            [
                {"path": "docs/", "isDir": 1, "size": None},
                {
                    "path": "docs/readme.txt",
                    "isDir": 0,
                    "size": 42,
                    "fingerprint": "local:sha256:test",
                },
            ],
        )

        emptyMeta = jobMapper.replaceSourceSnapshot(jobId, [])
        emptySnapshot = jobMapper.getSourceSnapshot(jobId)
        self.assertEqual(emptyMeta["initialized"], 1)
        self.assertEqual(emptySnapshot["meta"]["entryCount"], 0)
        self.assertEqual(emptySnapshot["entries"], [])

    def test_snapshot_replace_rolls_back_on_insert_error(self):
        jobId = jobMapper.addJob(self._job())
        jobMapper.replaceSourceSnapshot(
            jobId, [{"path": "stable.bin", "isDir": 0, "size": 7}]
        )
        before = jobMapper.getSourceSnapshot(jobId)

        with self.assertRaises(Exception):
            jobMapper.replaceSourceSnapshot(
                jobId,
                [{"path": "too-large.bin", "isDir": 0, "size": 2 ** 64}],
            )

        self.assertEqual(jobMapper.getSourceSnapshot(jobId), before)

    def test_stale_job_identity_cannot_overwrite_invalidated_snapshot(self):
        job = self._job(sourceMode=1)
        jobId = jobMapper.addJob(job)
        oldIdentity = jobMapper.sourceSnapshotIdentity(job)
        jobMapper.replaceSourceSnapshot(
            jobId, [{"path": "old.txt", "isDir": 0, "size": 7}]
        )
        job.update({"id": jobId, "srcPath": "/new-source/"})
        jobMapper.updateJob(job, clearSourceSnapshot=True)

        with self.assertRaises(Exception):
            jobMapper.replaceSourceSnapshot(
                jobId,
                [{"path": "stale.txt", "isDir": 0, "size": 8}],
                expectedIdentity=oldIdentity,
            )

        self.assertEqual(
            jobMapper.getSourceSnapshot(jobId)["meta"]["initialized"], 0
        )

    def test_clear_and_delete_job_remove_snapshot(self):
        firstJobId = jobMapper.addJob(self._job())
        jobMapper.replaceSourceSnapshot(
            firstJobId, [{"path": "one.txt", "isDir": 0, "size": 1}]
        )
        jobMapper.clearSourceSnapshot(firstJobId)
        self.assertEqual(
            jobMapper.getSourceSnapshot(firstJobId)["meta"]["initialized"], 0
        )

        secondJob = self._job(sourceMode=1)
        secondJob["srcPath"] = "/other-source/"
        secondJobId = jobMapper.addJob(secondJob)
        jobMapper.replaceSourceSnapshot(
            secondJobId, [{"path": "two.txt", "isDir": 0, "size": 2}]
        )
        jobMapper.deleteJob(secondJobId)

        with closing(sqlite3.connect(self.database)) as connection:
            entryCount = connection.execute(
                "select count(*) from job_source_snapshot where jobId=?", (secondJobId,)
            ).fetchone()[0]
            metaCount = connection.execute(
                "select count(*) from job_source_snapshot_meta where jobId=?", (secondJobId,)
            ).fetchone()[0]
        self.assertEqual(entryCount, 0)
        self.assertEqual(metaCount, 0)

        with self.assertRaises(Exception):
            jobMapper.replaceSourceSnapshot(
                secondJobId, [{"path": "late.txt", "isDir": 0, "size": 3}]
            )

        with closing(sqlite3.connect(self.database)) as connection:
            lateEntryCount = connection.execute(
                "select count(*) from job_source_snapshot where jobId=?", (secondJobId,)
            ).fetchone()[0]
        self.assertEqual(lateEntryCount, 0)

    def test_engine_configuration_change_invalidates_related_snapshots_only(self):
        firstJob = self._job()
        firstJobId = jobMapper.addJob(firstJob)
        secondJob = self._job()
        secondJob.update({
            "alistId": 2,
            "srcPath": "/second-source/",
            "dstPath": "/second-target/",
        })
        secondJobId = jobMapper.addJob(secondJob)
        jobMapper.replaceSourceSnapshot(
            firstJobId, [{"path": "first.txt", "isDir": 0, "size": 1}]
        )
        jobMapper.replaceSourceSnapshot(
            secondJobId, [{"path": "second.txt", "isDir": 0, "size": 2}]
        )

        jobMapper.clearSourceSnapshotsByEngine(1)

        self.assertEqual(
            jobMapper.getSourceSnapshot(firstJobId)["meta"]["initialized"], 0
        )
        self.assertEqual(
            jobMapper.getSourceSnapshot(secondJobId)["meta"]["initialized"], 1
        )


if __name__ == "__main__":
    unittest.main()
