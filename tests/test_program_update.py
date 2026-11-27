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

from apiServer.trust_manifest import encode_manifest, parse_builds, parse_latest, parse_manifest
from controller.updateController import ProgramUpload, UpdateCheck
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
