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

from apiServer.trust_manifest import encode_manifest, parse_manifest
from controller.updateController import ProgramUpload
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
        self.mirrors = self.enterContext(patch.object(update, 'fetch_manifest', side_effect=ValueError('offline')))
        self.auth = self.enterContext(patch.object(ProgramUpload, 'authenticated', return_value=True))
        self.restart = Mock()
        self.addCleanup(jobClient.cancelProgramUpdate)
        super().setUp()

    def get_app(self):
        return Application([('/update', ProgramUpload)], restart_for_update=self.restart)

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
        self.mirrors.assert_not_called()

    def test_zip_installs_nested_executable_with_offline_pin(self):
        body = release_archive('zip', ('release/taoSync.exe', PAYLOAD), ('release/notes.txt', b'notes'))
        self.assert_installed(self.upload(body=body))
        self.mirrors.assert_not_called()

    def test_tar_gz_installs_program_registered_for_current_platform(self):
        body = release_archive('tar.gz', ('notes.txt', b'notes'), ('./taoSync', PAYLOAD))
        self.mirrors.side_effect = None
        self.mirrors.return_value = [('v1', update.platform_target(), DIGEST)]
        with patch.dict(os.environ, TAO_UPDATE_SHA256=''):
            self.assert_installed(self.upload(body=body))
        self.mirrors.assert_awaited()

    def test_archive_hash_and_other_platform_executable_do_not_authorize_update(self):
        self.mirrors.side_effect = None
        for kind in ('tar.gz', 'zip'):
            with self.subTest(kind=kind):
                body = release_archive(kind, ('taoSync', PAYLOAD))
                outer = hashlib.sha256(body).hexdigest()
                self.mirrors.return_value = [('v1', 'other', DIGEST), ('v1', update.platform_target(), outer)]
                with patch.dict(os.environ, TAO_UPDATE_SHA256=outer):
                    res = self.upload(headers={**HEADERS, 'Accept-Language': 'en'}, body=body)
                self.assertEqual(res.code, 400)
                self.assertIn('not registered for this platform', json.loads(res.body)['msg'])
                self.assertEqual(list(self.directory.iterdir()), [])
        self.assertFalse((self.channel / 'request').exists())
        self.restart.assert_not_called()

    def test_rejects_missing_ambiguous_corrupt_and_oversized_archive_contents(self):
        for kind in ('tar.gz', 'zip'):
            valid = release_archive(kind, ('taoSync', PAYLOAD))
            for reason, body, code, message in (
                ('missing', release_archive(kind, ('notes', PAYLOAD)), 400, 'exactly one'),
                ('ambiguous', release_archive(kind, ('taoSync', PAYLOAD), ('bin/taoSync.exe', PAYLOAD)), 400, 'exactly one'),
                ('truncated', valid[:-16], 400, 'complete .tar.gz or .zip'),
                ('oversize', release_archive(kind, ('taoSync', bytes(2048))), 413, 'size limit'),
            ):
                with self.subTest(kind=kind, reason=reason), patch.object(update, 'MAX_BYTES', 1024):
                    self.assertLess(len(body), update.MAX_BYTES)
                    res = self.upload(headers={**HEADERS, 'Accept-Language': 'en'}, body=body)
                    self.assertEqual(res.code, code, res.body)
                    self.assertIn(message, json.loads(res.body)['msg'])
                    self.assertEqual(list(self.directory.iterdir()), [])
        self.mirrors.assert_not_called()
        self.assertFalse((self.channel / 'request').exists())
        self.restart.assert_not_called()

    def test_online_file_is_accepted_with_a_different_pin(self):
        self.mirrors.side_effect = None
        self.mirrors.return_value = [('v1-dev', update.platform_target(), DIGEST)]
        with patch.dict(os.environ, TAO_UPDATE_SHA256='a' * 64):
            self.assertEqual(self.upload().code, 200)
        self.restart.assert_called_once()

    def test_offline_pin_miss_never_stages_or_restarts(self):
        res = self.upload(headers={**HEADERS, 'Accept-Language': 'en'}, body=b'untrusted')
        self.assertEqual(res.code, 400)
        self.assertIn('Neither trust source', json.loads(res.body)['msg'])
        self.assertEqual(self.mirrors.await_count, 2)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.restart.assert_not_called()

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


class TrustRaceTest(unittest.IsolatedAsyncioTestCase):
    async def test_first_valid_list_wins_even_on_miss_and_closes_other_request(self):
        started, cancelled = asyncio.Event(), asyncio.Event()
        async def fetch(url):
            if url == 'https://taoapi.dr34m.cn/auth.json':
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    cancelled.set()
            self.assertEqual(url, 'https://dr34m-cn.github.io/taosync/auth.json')
            await started.wait()
            return [('v1', 'other', DIGEST)]
        with patch.dict(os.environ, TAO_UPDATE_SHA256=''), patch.object(update, 'fetch_manifest', fetch):
            with self.assertRaisesRegex(ValueError, 'update_not_trusted'):
                await asyncio.wait_for(update.verify_digest(DIGEST), 1)
        self.assertTrue(cancelled.is_set())

    async def test_bad_first_json_then_history_across_versions_with_optional_pin(self):
        sha2, pin = 'b' * 64, 'c' * 64
        async def fetch(url):
            if url == update.TRUST_URLS[0]:
                return parse_manifest(b'{"entries":[]}')
            await asyncio.sleep(0)
            return parse_manifest(encode_manifest([('v1-dev', 'target', DIGEST), ('v2-pre', 'target', sha2),
                                                    ('v2', 'wrong', 'd' * 64)]))
        with patch.object(update, 'fetch_manifest', fetch), patch.object(update, 'platform_target', return_value='target'):
            for configured in ('', 'typo', pin.upper()):
                with patch.dict(os.environ, TAO_UPDATE_SHA256=configured):
                    for digest in (DIGEST, sha2):
                        await update.verify_digest(digest)
                    with self.assertRaisesRegex(ValueError, 'update_not_trusted'):
                        await update.verify_digest('d' * 64)

    async def test_offline_only_valid_pin_can_allow_a_file(self):
        for pin in ('', 'invalid', DIGEST.upper()):
            with patch.dict(os.environ, TAO_UPDATE_SHA256=pin), patch.object(update, 'fetch_manifest', side_effect=ValueError) as get:
                if pin == DIGEST.upper():
                    await update.verify_digest(DIGEST)
                    get.assert_not_called()
                else:
                    with self.assertRaises(ValueError):
                        await update.verify_digest(DIGEST)
                    self.assertEqual(get.await_count, 2)


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
