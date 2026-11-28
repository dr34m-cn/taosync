import asyncio
import hashlib
import io
import json
import os
import runpy
import tarfile
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from apiServer.trust import snapshot as trust_snapshot
from apiServer.trust_manifest import (
    build_downloads_catalog,
    encode_manifest,
    load_download_sources,
    parse_builds,
    parse_latest,
    parse_latest_details,
    parse_manifest,
)
from controller.updateController import OnlineUpdate, ProgramUpload, UpdateCheck, UpdateReleases
from service.syncJob import jobClient
from service.system import programUpdate as update, updateLauncher as launcher

PAYLOAD = b'trusted test fixture, never executed'
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
HEADERS = {'Content-Type': 'application/octet-stream', 'X-TaoSync-Update': '1'}


def release_archive(kind, *files):
    output = io.BytesIO()
    if kind == 'zip':
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, content in files:
                archive.writestr(name, content)
    else:
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name, content in files:
                entry = tarfile.TarInfo(name)
                entry.size = len(content)
                archive.addfile(entry, io.BytesIO(content))
    return output.getvalue()


class UploadTest(AsyncHTTPTestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.directory = root / 'slots'
        self.channel = root
        self.enterContext(patch.dict(os.environ, TAO_UPDATE_CHANNEL=str(root),
                                     TAO_UPDATE_DIR=str(self.directory), TAO_UPDATE_SHA256=DIGEST))
        self.enterContext(patch.object(update.sys, 'frozen', True, create=True))
        self.mirrors = self.enterContext(patch.object(
            update, 'fetch_manifest_bytes',
            return_value=encode_manifest([('v1', update.platform_target(), DIGEST)], version='v1'),
        ))
        self.auth = self.enterContext(patch.object(ProgramUpload, 'authenticated', return_value=True))
        self.restart = Mock()
        self.addCleanup(jobClient.cancelProgramUpdate)
        super().setUp()

    def get_app(self):
        return Application([('/update', ProgramUpload), ('/check', UpdateCheck)], restart_for_update=self.restart)

    def upload(self, headers=HEADERS, body=PAYLOAD):
        return self.fetch('/update', method='POST', headers=headers, body=body)

    def assert_installed(self, res):
        self.assertEqual(res.code, 200, res.body)
        slot = launcher.slot(self.directory, DIGEST)
        self.assertEqual(list(self.directory.iterdir()), [slot])
        self.assertEqual(slot.read_bytes(), PAYLOAD)
        self.assertEqual(launcher.read_json(self.channel / 'request'),
                         {'id': json.loads(res.body)['data']['id'], 'digest': DIGEST})
        self.restart.assert_called_once()
        self.assertFalse(jobClient.acquireRun(threading.Lock()))

    def test_stages_only_the_verified_bytes_and_requests_restart(self):
        self.assert_installed(self.upload())
        self.mirrors.assert_awaited()

    def test_zip_installs_registered_nested_executable(self):
        body = release_archive('zip', ('release/taoSync.exe', PAYLOAD), ('release/notes.txt', b'notes'))
        self.assert_installed(self.upload(body=body))
        self.mirrors.assert_awaited()

    def test_tar_gz_installs_program_registered_for_current_platform(self):
        body = release_archive('tar.gz', ('notes.txt', b'notes'), ('./taoSync', PAYLOAD))
        self.mirrors.side_effect = None
        self.mirrors.return_value = encode_manifest([('v1', update.platform_target(), DIGEST)], version='v1')
        with patch.dict(os.environ, TAO_UPDATE_SHA256=''):
            self.assert_installed(self.upload(body=body))
        self.mirrors.assert_awaited()

    def test_archive_hash_and_other_platform_executable_do_not_authorize_update(self):
        self.mirrors.side_effect = None
        for kind in ('tar.gz', 'zip'):
            with self.subTest(kind=kind):
                body = release_archive(kind, ('taoSync', PAYLOAD))
                outer = hashlib.sha256(body).hexdigest()
                self.mirrors.return_value = encode_manifest(
                    [('v1', 'other', DIGEST), ('v1', update.platform_target(), outer)], version='v1'
                )
                with patch.dict(os.environ, TAO_UPDATE_SHA256=outer):
                    res = self.upload(body=body)
                self.assertEqual(res.code, 400)
                self.assertEqual(json.loads(res.body)['msg'],
                                 f'架构错误，本系统架构为{update.platform_target()}，更新包架构为other，请上传正确架构的更新包')
                self.assertEqual(list(self.directory.iterdir()), [])
        self.assertFalse((self.channel / 'request').exists())
        self.restart.assert_not_called()

    def test_rejects_missing_ambiguous_corrupt_and_oversized_archive_contents(self):
        for kind in ('tar.gz', 'zip'):
            valid = release_archive(kind, ('taoSync', PAYLOAD))
            for reason, body, code, message in (
                ('missing', release_archive(kind, ('notes', PAYLOAD)), 400, 'not trusted'),
                ('ambiguous', release_archive(kind, ('taoSync', PAYLOAD), ('bin/taoSync.exe', PAYLOAD)), 400, 'not trusted'),
                ('truncated', valid[:-16], 400, 'not trusted'),
                ('oversize', release_archive(kind, ('taoSync', bytes(2048))), 413, 'size limit'),
            ):
                with self.subTest(kind=kind, reason=reason), patch.object(update, 'MAX_BYTES', 1024):
                    self.assertLess(len(body), update.MAX_BYTES)
                    res = self.upload(headers={**HEADERS, 'Accept-Language': 'en'}, body=body)
                    self.assertEqual(res.code, code, res.body)
                    self.assertIn(message, json.loads(res.body)['msg'])
                    self.assertEqual(list(self.directory.iterdir()), [])
        self.assertFalse((self.channel / 'request').exists())
        self.restart.assert_not_called()

    def test_online_file_is_accepted_with_a_different_pin(self):
        self.mirrors.side_effect = None
        self.mirrors.return_value = encode_manifest([('v1-dev', update.platform_target(), DIGEST)])
        with patch.dict(os.environ, TAO_UPDATE_SHA256='a' * 64):
            self.assertEqual(self.upload().code, 200)
        self.restart.assert_called_once()

    def test_offline_even_matching_pin_never_stages_or_restarts(self):
        self.mirrors.side_effect = ValueError('offline')
        res = self.upload(headers={**HEADERS, 'Accept-Language': 'en'})
        self.assertEqual(res.code, 400)
        self.assertIn('Neither trust source', json.loads(res.body)['msg'])
        self.assertEqual(self.mirrors.await_count, 2)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.restart.assert_not_called()

    def test_unlisted_file_and_registered_apk(self):
        self.mirrors.return_value = encode_manifest([])
        self.assertEqual(json.loads(self.upload().body)['msg'], '文件不可信，请仅在可信位置下载更新包')
        apk = release_archive('zip', ('AndroidManifest.xml', b'test'))
        self.mirrors.return_value = encode_manifest([('v1', 'android-arm64', hashlib.sha256(apk).hexdigest())], version='v1')
        response = self.upload(headers={**HEADERS, 'Accept-Language': 'en'}, body=apk)
        self.assertIn('Architecture mismatch', json.loads(response.body)['msg'])
        self.assertIn('android-arm64', json.loads(response.body)['msg'])
        self.restart.assert_not_called()

    def test_update_check_endpoint_requires_auth_and_compares_versions(self):
        with patch.object(UpdateCheck, 'authenticated_user', return_value=None):
            res = self.fetch('/check', headers={'Authorization': 't-' + '0' * 64})
            self.assertEqual(res.code, 401)
        with patch.object(UpdateCheck, 'authenticated_user', return_value={'id': 1, 'userName': 'admin'}), \
                patch.object(update, 'current_version', return_value='v0.5.1'):
            self.mirrors.side_effect = None
            self.mirrors.return_value = encode_manifest([('v0.5.2', 'linux-amd64', DIGEST)], version='v0.5.2')
            res = self.fetch('/check')
            self.assertEqual(res.code, 200)
            self.assertEqual(json.loads(res.body)['data'], {
                'currentVersion': 'v0.5.1', 'latestVersion': 'v0.5.2', 'hasUpdate': True, 'checked': True,
            })
            self.mirrors.return_value = encode_manifest([('v0.5.1', 'linux-amd64', DIGEST)], version='v0.5.1')
            same = json.loads(self.fetch('/check').body)['data']
            self.assertEqual(same['hasUpdate'], False)
            self.assertEqual(same['latestVersion'], 'v0.5.1')
            self.mirrors.side_effect = ValueError('offline')
            offline = json.loads(self.fetch('/check').body)['data']
            self.assertEqual(offline, {
                'currentVersion': 'v0.5.1', 'latestVersion': None, 'hasUpdate': False, 'checked': False,
            })

    def test_authentication_and_non_simple_request_required_before_staging(self):
        self.auth.return_value = False
        self.assertEqual(self.upload().code, 401)
        self.auth.return_value = True
        self.assertEqual(self.upload(headers={'Content-Type': 'text/plain'}).code, 403)
        with patch.object(update.sys, 'frozen', False):
            self.assertEqual(self.upload().code, 409)
        self.assertFalse(self.directory.exists())

    def test_size_hash_busy_and_failed_commit_do_not_restart(self):
        with patch.object(update, 'MAX_BYTES', 2):
            self.assertEqual(self.upload().code, 413)
        self.assertEqual(self.upload(body=b'wrong').code, 400)
        run = threading.Lock()
        self.assertTrue(jobClient.acquireRun(run))
        self.assertEqual(self.upload().code, 400)
        run.release()
        with patch.object(launcher, 'write_json', side_effect=OSError('disk full')):
            self.assertEqual(self.upload().code, 507)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.assertTrue(jobClient.acquireRun(run))
        run.release()
        self.restart.assert_not_called()


class ReleaseTest(unittest.TestCase):
    def test_manifest_hashes_extracted_artifact_for_each_archive_format(self):
        manifest = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/release-checksums.py'))['manifest']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for target, name in [('windows-amd64', 'taoSync.exe'), ('linux-StaticX-arm32', 'taoSync')]:
                with zipfile.ZipFile(root / f'taoSync-v1-{target}.zip', 'w') as archive:
                    archive.writestr(name, PAYLOAD)
            for target, name in [('darwin-arm64', './taoSync'), ('linux-arm-v7', 'taoSync')]:
                with tarfile.open(root / f'taoSync-v1-{target}.tar.gz', 'w:gz') as archive:
                    entry = tarfile.TarInfo(name)
                    entry.size = len(PAYLOAD)
                    archive.addfile(entry, io.BytesIO(PAYLOAD))
            self.assertCountEqual(list(manifest(root, 'v1')), [(DIGEST, target) for target in
                             ('darwin-arm64', 'linux-StaticX-arm32', 'linux-arm-v7', 'windows-amd64')])

            (root / 'taoSync-v1-android-debug.apk').write_bytes(PAYLOAD)
            self.assertIn((DIGEST, 'android-arm64-v8a+armeabi-v7a'), list(manifest(root, 'v1', True)))

    def test_split_migrates_mixed_manifest_into_stable_dev_and_latest(self):
        import subprocess
        import sys
        script = Path(__file__).resolve().parents[1] / 'scripts/release-checksums.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / 'legacy.json'
            delta = root / 'delta.json'
            stable_out = root / 'auth.json'
            dev_out = root / 'auth-dev.json'
            latest_out = root / 'latest.json'
            legacy.write_bytes(encode_manifest([
                ('v0.5.1-dev-test-build3', 'linux-amd64', '1' * 64, '2026-11-20T01:00:00Z'),
                ('v0.5.1-pre-build0', 'linux-amd64', '2' * 64, '2026-11-21T01:00:00Z'),
                ('v0.5.0', 'linux-amd64', '3' * 64, '2026-11-18T01:00:00Z'),
                ('v0.5.1', 'linux-amd64', '4' * 64, '2026-11-22T01:00:00Z'),
            ]))
            delta.write_bytes(encode_manifest([
                ('v0.5.2', 'linux-amd64', '5' * 64, '2026-11-27T01:00:00Z'),
                ('v0.5.2', 'windows-amd64', '6' * 64, '2026-11-27T01:00:00Z'),
            ]))
            subprocess.run([sys.executable, str(script), 'split',
                            str(stable_out), str(dev_out), str(latest_out), str(legacy), str(delta)], check=True)
            self.assertEqual(parse_manifest(stable_out.read_bytes()), [
                ('v0.5.0', 'linux-amd64', '3' * 64),
                ('v0.5.1', 'linux-amd64', '4' * 64),
                ('v0.5.2', 'linux-amd64', '5' * 64),
                ('v0.5.2', 'windows-amd64', '6' * 64),
            ])
            self.assertEqual(parse_manifest(dev_out.read_bytes()), [
                ('v0.5.1-dev-test-build3', 'linux-amd64', '1' * 64),
                ('v0.5.1-pre-build0', 'linux-amd64', '2' * 64),
            ])
            self.assertEqual(parse_latest(latest_out.read_bytes()), ('v0.5.2', [
                ('v0.5.2', 'linux-amd64', '5' * 64),
                ('v0.5.2', 'windows-amd64', '6' * 64),
            ]))

            # Verify apiServer /latest.json matches GitHub Pages static latest.json byte-for-byte.
            db_path = root / 'trust.db'
            trust_snapshot(db_path, stable_out.read_bytes())
            trust_snapshot(db_path, dev_out.read_bytes())
            self.assertEqual(trust_snapshot(db_path, kind='latest'), latest_out.read_bytes())
            ver, _, downloads = parse_latest_details(latest_out.read_bytes())
            self.assertEqual(ver, 'v0.5.2')
            self.assertEqual(
                [(item['version'], item['channel'], [s['id'] for s in item['sources']]) for item in downloads['versions']],
                [
                    ('v0.5.2', 'stable', ['github', 'r2']),
                    ('v0.5.1', 'stable', ['github', 'r2']),
                    ('v0.5.0', 'stable', ['github', 'r2']),
                    ('v0.5.1-pre-build0', 'dev', ['r2']),
                    ('v0.5.1-dev-test-build3', 'dev', ['r2']),
                ],
            )


class PublishR2Test(unittest.TestCase):
    def setUp(self):
        self.mod = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/publish-r2.py'))

    def test_version_classification_and_target_prefixes(self):
        self.assertEqual(self.mod['target_prefix']('v0.5.2'), 'taosync-release/v0.5.2/')
        self.assertEqual(self.mod['target_prefix']('v0.5.2-dev-test-build4'), 'taosync-release/dev/v0.5.2-dev-test-build4/')
        self.assertEqual(self.mod['target_prefix']('v0.5.2-pre-build0'), 'taosync-release/dev/v0.5.2-pre-build0/')
        self.assertEqual(self.mod['target_prefix']('v0.5.2-beta.1'), 'taosync-release/dev/v0.5.2-beta.1/')
        for invalid in ('dev', 'DEV', '../bad', 'a/b'):
            with self.assertRaises(ValueError):
                self.mod['target_prefix'](invalid)

    def test_retention_keeps_latest_3_stable_and_2_dev_only(self):
        objects = [
            {'Key': 'taosync-release/v0.5.0/taoSync-v0.5.0-linux-amd64.tar.gz', 'LastModified': '2026-11-01T00:00:00Z'},
            {'Key': 'taosync-release/v0.5.1/taoSync-v0.5.1-linux-amd64.tar.gz', 'LastModified': '2026-11-02T00:00:00Z'},
            {'Key': 'taosync-release/v0.5.2/taoSync-v0.5.2-linux-amd64.tar.gz', 'LastModified': '2026-11-03T00:00:00Z'},
            {'Key': 'taosync-release/v0.5.3/taoSync-v0.5.3-linux-amd64.tar.gz', 'LastModified': '2026-11-04T00:00:00Z'},
            {'Key': 'taosync-release/dev/v0.5.4-dev-build1/taoSync.tar.gz', 'LastModified': '2026-11-05T00:00:00Z'},
            {'Key': 'taosync-release/dev/v0.5.4-beta.1/taoSync.tar.gz', 'LastModified': '2026-11-06T00:00:00Z'},
            {'Key': 'taosync-release/dev/v0.5.4-pre-build2/taoSync.tar.gz', 'LastModified': '2026-11-07T00:00:00Z'},
            {'Key': 'other-folder/keep.txt', 'LastModified': '2026-11-01T00:00:00Z'},
        ]
        pruned = self.mod['select_pruned_prefixes'](objects, current_version='v0.5.4-pre-build2')
        self.assertEqual(pruned, ['taosync-release/v0.5.0/', 'taosync-release/dev/v0.5.4-dev-build1/'])

    def test_publish_to_r2_syncs_and_prunes_via_aws_cli(self):
        calls = []

        def fake_run(cmd, env=None, check=True, text=True, capture_output=False):
            calls.append((cmd, env))
            if 'list-objects-v2' in cmd:
                body = json.dumps({
                    'IsTruncated': False,
                    'Contents': [
                        {'Key': 'taosync-release/dev/v0.5.2-dev1/a.tar.gz', 'LastModified': '2026-11-01T00:00:00Z'},
                        {'Key': 'taosync-release/dev/v0.5.2-dev2/a.tar.gz', 'LastModified': '2026-11-02T00:00:00Z'},
                        {'Key': 'taosync-release/dev/v0.5.2-dev3/a.tar.gz', 'LastModified': '2026-11-03T00:00:00Z'},
                    ],
                })
                return Mock(stdout=body)
            return Mock(stdout='')

        with tempfile.TemporaryDirectory() as tmp, patch('subprocess.run', side_effect=fake_run):
            dist = Path(tmp) / 'dist'
            dist.mkdir()
            (dist / 'taoSync-v0.5.2-dev3-linux-amd64.tar.gz').write_bytes(b'data')
            prefix, pruned = self.mod['publish_to_r2'](
                dist, 'v0.5.2-dev3',
                endpoint='https://example.r2.cloudflarestorage.com',
                bucket='my-bucket',
                access_key_id='key',
                secret_access_key='secret',
            )
        self.assertEqual(prefix, 'taosync-release/dev/v0.5.2-dev3/')
        self.assertEqual(pruned, ['taosync-release/dev/v0.5.2-dev1/'])
        self.assertEqual(calls[0][0][:3], ['aws', 's3', 'sync'])
        self.assertEqual(calls[0][0][4], 's3://my-bucket/taosync-release/dev/v0.5.2-dev3/')
        self.assertEqual(calls[0][1]['AWS_REQUEST_CHECKSUM_CALCULATION'], 'when_required')
        self.assertEqual(calls[2][0][:4], ['aws', 's3', 'rm', 's3://my-bucket/taosync-release/dev/v0.5.2-dev1/'])


class OnlineUpdateTest(AsyncHTTPTestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.directory = root / 'slots'
        self.channel = root
        self.target = 'linux-amd64'
        self.stable_payload = b'stable-binary-v0.5.2'
        self.stable_digest = hashlib.sha256(self.stable_payload).hexdigest()
        self.dev_payload = b'dev-binary-v0.5.3-dev1'
        self.dev_digest = hashlib.sha256(self.dev_payload).hexdigest()
        self.old_payload = b'old-binary-v0.5.1'
        self.old_digest = hashlib.sha256(self.old_payload).hexdigest()
        self.enterContext(patch.dict(os.environ, TAO_UPDATE_CHANNEL=str(root), TAO_UPDATE_DIR=str(self.directory)))
        self.enterContext(patch.object(update.sys, 'frozen', True, create=True))
        self.enterContext(patch.object(update, 'platform_target', return_value=self.target))
        self.enterContext(patch.object(update, 'current_version', return_value='v0.5.1'))
        self.enterContext(patch.object(OnlineUpdate, 'restart_delay', 0))
        self.enterContext(patch.object(UpdateReleases, 'authenticated_user', return_value={'id': 1, 'userName': 'admin'}))
        self.enterContext(patch.object(OnlineUpdate, 'authenticated', return_value=True))
        self.restart = Mock()
        OnlineUpdate.reset()
        self.addCleanup(OnlineUpdate.reset)
        self.addCleanup(jobClient.cancelProgramUpdate)
        super().setUp()

    def get_app(self):
        return Application(
            [('/releases', UpdateReleases), ('/online', OnlineUpdate), ('/upload', ProgramUpload)],
            restart_for_update=self.restart,
        )

    def _manifest_fetcher(self, download_sources=None):
        sources = download_sources or load_download_sources()
        stable_rows = [
            ('v0.5.1', self.target, self.old_digest, '2026-11-20T00:00:00Z'),
            ('v0.5.2', self.target, self.stable_digest, '2026-11-25T00:00:00Z'),
            ('v0.5.2', 'windows-amd64', 'f' * 64, '2026-11-25T00:00:00Z'),
        ]
        dev_rows = [
            ('v0.5.3-dev1', self.target, self.dev_digest, '2026-11-27T00:00:00Z'),
            ('v0.5.3-dev2', 'windows-amd64', 'e' * 64, '2026-11-28T00:00:00Z'),
        ]
        latest_rows = [row for row in stable_rows if row[0] == 'v0.5.2']
        downloads = build_downloads_catalog(stable_rows, dev_rows, sources)
        docs = {
            'latest.json': encode_manifest(latest_rows, version='v0.5.2', downloads=downloads),
            'auth.json': encode_manifest(stable_rows, download_sources=sources),
            'auth-dev.json': encode_manifest(dev_rows, download_sources=sources),
        }

        async def fetch(url):
            name = url.rsplit('/', 1)[-1]
            return docs[name]

        return fetch

    def _wait_online_done(self):
        async def wait_task():
            if OnlineUpdate.active_task is not None:
                await OnlineUpdate.active_task
        self.io_loop.run_sync(wait_task)

    def test_releases_endpoint_filters_by_platform_and_returns_channel_sources(self):
        with patch.object(update, 'fetch_manifest_bytes', self._manifest_fetcher()):
            res = self.fetch('/releases')
        self.assertEqual(res.code, 200, res.body)
        data = json.loads(res.body)['data']
        self.assertEqual(data['latestVersion'], 'v0.5.2')
        self.assertTrue(data['latestAvailable'])
        self.assertEqual([v['version'] for v in data['versions']], ['v0.5.2', 'v0.5.1', 'v0.5.3-dev1'])
        self.assertEqual([s['id'] for s in data['versions'][0]['sources']], ['github', 'r2'])
        self.assertEqual(
            data['versions'][0]['sources'][1]['url'],
            'https://cdn.20240303.xyz/taosync-release/v0.5.2/taoSync-v0.5.2-linux-amd64.tar.gz',
        )
        self.assertEqual([s['id'] for s in data['versions'][2]['sources']], ['r2'])
        self.assertEqual(
            data['versions'][2]['sources'][0]['url'],
            'https://cdn.20240303.xyz/taosync-release/dev/v0.5.3-dev1/taoSync-v0.5.3-dev1-linux-amd64.tar.gz',
        )

    def test_online_update_auto_source_races_cancels_slower_and_installs_latest(self):
        slow_started = asyncio.Event()
        slow_cancelled = asyncio.Event()
        downloaded_urls = []
        archive = release_archive('tar.gz', ('taoSync', self.stable_payload))

        async def fake_probe(source, **_kwargs):
            if source['id'] == 'github':
                slow_started.set()
                try:
                    await asyncio.Future()
                finally:
                    slow_cancelled.set()
            await slow_started.wait()
            return source, 42

        async def fake_download(url, destination, *, limit=update.MAX_BYTES, on_progress=None):
            downloaded_urls.append(url)
            Path(destination).write_bytes(archive)
            if on_progress:
                on_progress(len(archive), len(archive))
            return hashlib.sha256(archive).hexdigest()

        with patch.object(update, 'fetch_manifest_bytes', self._manifest_fetcher()), \
                patch.object(update, 'probe_source', fake_probe), \
                patch.object(update, 'download_package', fake_download):
            res = self.fetch(
                '/online', method='POST',
                headers={'X-TaoSync-Update': '1', 'Content-Type': 'application/json'},
                body=json.dumps({'version': 'latest', 'source': 'auto'}),
            )
            self.assertEqual(res.code, 200, res.body)
            started = json.loads(res.body)['data']
            self.assertEqual(started['version'], 'v0.5.2')
            self._wait_online_done()

        self.assertTrue(slow_cancelled.is_set())
        self.assertEqual(downloaded_urls, [
            'https://cdn.20240303.xyz/taosync-release/v0.5.2/taoSync-v0.5.2-linux-amd64.tar.gz',
        ])
        slot = launcher.slot(self.directory, self.stable_digest)
        self.assertEqual(slot.read_bytes(), self.stable_payload)
        self.assertEqual(launcher.read_json(self.channel / 'request'),
                         {'id': started['id'], 'digest': self.stable_digest})
        self.restart.assert_called_once()

    def test_online_update_dev_version_uses_r2_and_rejects_version_mismatch(self):
        dev_archive = release_archive('tar.gz', ('taoSync', self.dev_payload))
        wrong_archive = release_archive('tar.gz', ('taoSync', self.old_payload))

        async def download_wrong(url, destination, **_kwargs):
            Path(destination).write_bytes(wrong_archive)
            return hashlib.sha256(wrong_archive).hexdigest()

        with patch.object(update, 'fetch_manifest_bytes', self._manifest_fetcher()), \
                patch.object(update, 'download_package', download_wrong):
            res = self.fetch(
                '/online', method='POST',
                headers={'X-TaoSync-Update': '1', 'Content-Type': 'application/json'},
                body=json.dumps({'version': 'v0.5.3-dev1', 'source': 'r2'}),
            )
            self.assertEqual(res.code, 200)
            self._wait_online_done()
            status = json.loads(self.fetch('/online', headers={'Accept-Language': 'en'}).body)['data']
        self.assertEqual(status['phase'], 'error')
        self.assertIn('does not match the selected version', status['message'])
        self.restart.assert_not_called()

        async def download_dev(url, destination, **_kwargs):
            self.assertIn('/taosync-release/dev/v0.5.3-dev1/', url)
            Path(destination).write_bytes(dev_archive)
            return hashlib.sha256(dev_archive).hexdigest()

        with patch.object(update, 'fetch_manifest_bytes', self._manifest_fetcher()), \
                patch.object(update, 'download_package', download_dev):
            res = self.fetch(
                '/online', method='POST',
                headers={'X-TaoSync-Update': '1', 'Content-Type': 'application/json'},
                body=json.dumps({'version': 'v0.5.3-dev1', 'source': 'auto'}),
            )
            self.assertEqual(res.code, 200)
            self._wait_online_done()
        self.assertEqual(launcher.slot(self.directory, self.dev_digest).read_bytes(), self.dev_payload)
        self.restart.assert_called_once()

    def test_online_update_can_be_cancelled_and_blocks_concurrent_start(self):
        started = asyncio.Event()

        async def slow_download(url, destination, **_kwargs):
            started.set()
            await asyncio.Future()

        with patch.object(update, 'fetch_manifest_bytes', self._manifest_fetcher()), \
                patch.object(update, 'download_package', slow_download):
            res = self.fetch(
                '/online', method='POST',
                headers={'X-TaoSync-Update': '1', 'Content-Type': 'application/json'},
                body=json.dumps({'version': 'v0.5.3-dev1', 'source': 'r2'}),
            )
            self.assertEqual(res.code, 200)
            self.io_loop.run_sync(started.wait)
            busy = self.fetch(
                '/online', method='POST',
                headers={'X-TaoSync-Update': '1', 'Content-Type': 'application/json'},
                body=json.dumps({'version': 'latest', 'source': 'auto'}),
            )
            self.assertEqual(busy.code, 409)
            cancel = self.fetch('/online', method='DELETE', headers={'X-TaoSync-Update': '1'})
            self.assertEqual(cancel.code, 200)
            self._wait_online_done()
            status = json.loads(self.fetch('/online').body)['data']
        self.assertEqual(status['phase'], 'cancelled')
        self.assertEqual(list(self.directory.iterdir()), [])
        self.restart.assert_not_called()


class TrustRaceTest(unittest.IsolatedAsyncioTestCase):
    async def test_latest_match_closes_other_origin_and_skips_history(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        requested = []

        async def fetch(url):
            requested.append(url)
            if url == 'https://taoapi.dr34m.cn/latest.json':
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    cancelled.set()
            self.assertEqual(url, 'https://dr34m-cn.github.io/taosync/latest.json')
            await started.wait()
            return encode_manifest([('v1', update.platform_target(), DIGEST)], version='v1')

        with patch.dict(os.environ, TAO_UPDATE_SHA256=''), patch.object(update, 'fetch_manifest_bytes', fetch):
            await asyncio.wait_for(update.verify_digest(DIGEST), 1)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(set(requested), {
            'https://taoapi.dr34m.cn/latest.json',
            'https://dr34m-cn.github.io/taosync/latest.json',
        })

    async def test_miss_in_latest_checks_auth_then_auth_dev_on_winning_origin_only(self):
        stable_sha, dev_sha, wrong_arch_sha = 'a' * 64, 'b' * 64, 'd' * 64
        winning = update.TRUST_ORIGINS[1]
        for digest, expected_tail, should_fail in (
            (stable_sha, [f'{winning}/auth.json'], None),
            (dev_sha, [f'{winning}/auth.json', f'{winning}/auth-dev.json'], None),
            (wrong_arch_sha, [f'{winning}/auth.json', f'{winning}/auth-dev.json'], update.ArchitectureMismatch),
            ('f' * 64, [f'{winning}/auth.json', f'{winning}/auth-dev.json'], ValueError),
        ):
            with self.subTest(digest=digest):
                started, cancelled = asyncio.Event(), asyncio.Event()
                followups = []

                async def fetch(url):
                    if url == f'{update.TRUST_ORIGINS[0]}/latest.json':
                        started.set()
                        try:
                            await asyncio.Future()
                        finally:
                            cancelled.set()
                    if url == f'{winning}/latest.json':
                        await started.wait()
                        return encode_manifest([('v2', 'target', '9' * 64)], version='v2')
                    self.assertTrue(url.startswith(winning + '/'), url)
                    followups.append(url)
                    if url.endswith('/auth.json'):
                        return encode_manifest([('v1', 'target', stable_sha), ('v2', 'wrong', wrong_arch_sha)])
                    if url.endswith('/auth-dev.json'):
                        return encode_manifest([('v2-dev', 'target', dev_sha)])
                    raise AssertionError(url)

                with patch.object(update, 'fetch_manifest_bytes', fetch), \
                        patch.object(update, 'platform_target', return_value='target'):
                    if should_fail is None:
                        await update.verify_digest(digest)
                    else:
                        with self.assertRaises(should_fail) as caught:
                            await update.verify_digest(digest)
                        if should_fail is ValueError:
                            self.assertEqual(str(caught.exception), 'update_not_trusted')
                self.assertTrue(cancelled.is_set())
                self.assertEqual(followups, expected_tail)

    async def test_bad_first_latest_uses_other_origin_and_checks_dev_when_auth_fails(self):
        dev_sha = 'e' * 64
        winning = update.TRUST_ORIGINS[1]

        async def fetch(url):
            if url == f'{update.TRUST_ORIGINS[0]}/latest.json':
                return b'{"entries":[]}'
            await asyncio.sleep(0)
            if url == f'{winning}/latest.json':
                return encode_manifest([('v2', 'target', '9' * 64)], version='v2')
            if url == f'{winning}/auth.json':
                raise ValueError('manifest unavailable')
            if url == f'{winning}/auth-dev.json':
                return encode_manifest([('v2-dev', 'target', dev_sha)])
            raise AssertionError(url)

        with patch.object(update, 'fetch_manifest_bytes', fetch), \
                patch.object(update, 'platform_target', return_value='target'):
            await update.verify_digest(dev_sha)
            with self.assertRaises(ValueError) as caught:
                await update.verify_digest('0' * 64)
            self.assertEqual(str(caught.exception), 'update_trust_unavailable')

    async def test_check_latest_version_cancels_slower_origin(self):
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def fetch(url):
            if url == f'{update.TRUST_ORIGINS[0]}/latest.json':
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    cancelled.set()
            await started.wait()
            return encode_manifest([('v0.6.0', 'linux-amd64', DIGEST)], version='v0.6.0')

        with patch.object(update, 'fetch_manifest_bytes', fetch), \
                patch.object(update, 'current_version', return_value='v0.5.2-dev-test-build3'):
            result = await asyncio.wait_for(update.check_latest_version(), 1)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(result, {
            'currentVersion': 'v0.5.2-dev-test-build3',
            'latestVersion': 'v0.6.0',
            'hasUpdate': True,
            'checked': True,
        })


class LauncherTest(unittest.TestCase):
    def simulate(self, fail=False, corrupt=False):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        base = root / 'taoSync'
        base.write_bytes(b'original')
        directory = root / '.taoSync-updates'
        directory.mkdir()
        target = launcher.slot(directory, DIGEST)
        target.write_bytes(b'invalid' if corrupt else PAYLOAD)
        commands = []
        def spawn(command, env, **kwargs):
            commands.append(Path(command[0]))
            channel = Path(env['TAO_UPDATE_CHANNEL'])
            child = Mock()
            child.returncode = 0
            if len(commands) == 1:
                launcher.write_json(channel / 'request', {'id': 'test', 'digest': DIGEST})
                child.returncode = launcher.RESTART
            elif commands[-1] == target and not fail:
                (channel / 'ready').touch()
            child.poll.return_value = child.returncode
            if commands[-1] == target and not fail:
                child.poll.side_effect = [None, 0, 0]
            return child
        results = []
        write = launcher.write_json
        def record(path, value):
            write(path, value)
            if path.name == 'result':
                results.append(value)
        with patch.object(launcher.subprocess, 'Popen', side_effect=spawn), patch.object(launcher.signal, 'signal'), \
                patch.object(launcher, 'write_json', side_effect=record):
            self.assertEqual(launcher.supervise(base, []), 0)
        self.assertEqual(base.read_bytes(), b'original')
        return commands, base, target, results, launcher.read_json(directory / 'active.json')

    def test_healthy_new_worker_becomes_active(self):
        cmds, base, target, result, state = self.simulate()
        self.assertEqual(cmds, [base, target])
        self.assertEqual(result, [{'id': 'test', 'status': 'started'}])
        self.assertEqual(state['active'], DIGEST)
        self.assertEqual(state['result'], result[0])

    def test_failed_start_and_tampering_relaunch_original(self):
        for corrupt in (True, False):
            cmds, base, target, result, state = self.simulate(fail=True, corrupt=corrupt)
            self.assertEqual(cmds, [base, base] if corrupt else [base, target, base])
            self.assertEqual(result, [{'id': 'test', 'status': 'rollback'}])
            self.assertIsNone(state['active'])
            self.assertEqual(state['result'], result[0])
