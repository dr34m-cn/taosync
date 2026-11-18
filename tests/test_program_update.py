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

from controller.updateController import ProgramUpload
from service.syncJob import jobClient
from service.system import programUpdate as update, updateLauncher as launcher

PAYLOAD = b'trusted test fixture, never executed'
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
HEADERS = {'Content-Type': 'application/octet-stream', 'X-TaoSync-Update': '1'}


class UploadTest(AsyncHTTPTestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.directory = root / 'slots'
        self.channel = root
        self.enterContext(patch.dict(os.environ, TAO_UPDATE_CHANNEL=str(root),
                                     TAO_UPDATE_DIR=str(self.directory), TAO_UPDATE_SHA256=DIGEST))
        self.enterContext(patch.object(update.sys, 'frozen', True, create=True))
        self.auth = self.enterContext(patch.object(ProgramUpload, 'authenticated', return_value=True))
        self.restart = Mock()
        self.addCleanup(jobClient.cancelProgramUpdate)
        super().setUp()

    def get_app(self):
        return Application([('/update', ProgramUpload)], restart_for_update=self.restart)

    def upload(self, headers=HEADERS, body=PAYLOAD):
        return self.fetch('/update', method='POST', headers=headers, body=body)

    def test_stages_only_the_verified_bytes_and_requests_restart(self):
        res = self.upload()
        self.assertEqual(res.code, 200, res.body)
        self.assertEqual(launcher.slot(self.directory, DIGEST).read_bytes(), PAYLOAD)
        self.assertEqual(launcher.read_json(self.channel / 'request'),
                         {'id': json.loads(res.body)['data']['id'], 'digest': DIGEST})
        self.restart.assert_called_once()
        self.assertFalse(jobClient.acquireRun(threading.Lock()))

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
            self.assertEqual(self.upload().code, 400)
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

    def test_only_trusts_matching_target_in_official_manifest(self):
        with patch.dict(os.environ, {'TAO_UPDATE_SHA256': ''}), patch.object(update.requests, 'get') as get, \
                patch.object(update, 'platform_target', return_value='linux-arm-v7'):
            response = get.return_value.__enter__.return_value
            response.raw.read.return_value = f'{DIGEST} linux-arm-v7\n'.encode()
            self.assertEqual(update.trusted_digest('v1'), DIGEST)
            self.assertEqual(get.call_args.args, (update.RELEASES + '/download/v1/taoSync-checksums.txt',))
            response.raw.read.return_value = f'{DIGEST} linux-amd64\n'.encode()
            with self.assertRaises(ValueError):
                update.trusted_digest('')
            with self.assertRaises(ValueError):
                update.trusted_digest('../untrusted')


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
