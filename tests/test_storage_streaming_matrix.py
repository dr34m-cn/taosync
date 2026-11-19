"""Run with: python -m unittest discover -s tests -p test_storage_streaming_matrix.py -v

The matrix uses the real driver transfer methods, TempDirectory local storage,
protocol-level memory peers and a non-seekable OS pipe. The socket tests use
Paramiko and, when available, pyftpdlib (optional test-only dependency).
"""

import ftplib
import hashlib
import io
import logging
import os
import socketserver
import tempfile
import threading
import unittest
from contextlib import contextmanager, nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

import paramiko

from service.storage.drivers.aliyun import _PartReader
from service.storage.drivers.base import StorageDriver, stream_transfer
from service.storage.drivers.crypt import CryptDriver
from service.storage.drivers.ftp import FtpDriver
from service.storage.drivers.local import LocalDriver
from service.storage.drivers.sftp import SftpDriver
from service.storage.drivers.smb import SmbDriver

# unittest discovery adds tests/ to sys.path. Reuse the protocol fixtures from
# the driver suites rather than replacing upload(), download() or stream_transfer().
from test_aliyun_transfer import make_driver as make_aliyun
from test_sftp_driver import _FakeSftp, _config as sftp_config
from test_smb_driver import _Client as MemorySmb


class MemoryFtp:
    def __init__(self, payload):
        self.files = {'/source': payload}

    def mlsd(self, path):
        assert path == '/'
        return [(k[1:], {'type': 'file', 'size': str(len(v))}) for k, v in self.files.items()]

    def voidcmd(self, cmd):
        assert cmd == 'TYPE I'

    def size(self, path):
        return len(self.files[path])

    def retrbinary(self, cmd, callback, blocksize):
        op, path = cmd.split(' ', 1)
        assert op == 'RETR'
        source = io.BytesIO(self.files[path])
        while chunk := source.read(min(blocksize, 17011)):
            callback(chunk)

    def storbinary(self, cmd, source, blocksize, callback):
        op, path = cmd.split(' ', 1)
        assert op == 'STOR'
        data = io.BytesIO()
        while chunk := source.read(blocksize):
            data.write(chunk)
            callback(chunk)
        self.files[path] = data.getvalue()

    def rename(self, source, destination):
        self.files[destination] = self.files.pop(source)

    def delete(self, path):
        if path not in self.files:
            raise ftplib.error_perm('550 missing')
        del self.files[path]


class MemoryAliyun:
    """Independent object bytes become visible only on OpenFile complete."""

    def __init__(self, payload):
        self.files = {'source': payload}
        self.parts = {}
        self.driver = make_aliyun()
        self.driver.rapid_upload = False
        self.driver.PART_SIZE = 384 * 1024 + 1  # exercise multiple part URLs in a small fixture
        self.driver._resolve.side_effect = self.resolve
        self.driver._request = self.request
        self.driver.session.get = self.get
        self.driver.session.put = self.put
        self.driver.session.request = Mock(side_effect=AssertionError('unexpected external request'))

    def resolve(self, path, **kwargs):
        if path == '/':
            return {'file_id': 'parent', 'type': 'folder'}
        name = path.lstrip('/')
        return {'file_id': name, 'type': 'file', 'name': name, 'size': len(self.files[name])}

    def request(self, endpoint, data):
        if endpoint.endswith('/getDownloadUrl'):
            return {'url': data['file_id']}
        if endpoint.endswith('/create'):
            self.parts.clear()
            parts = [dict(part, upload_url=str(part['part_number'])) for part in data['part_info_list']]
            return {'upload_id': 'session', 'file_id': data['name'], 'part_info_list': parts}
        if endpoint.endswith('/complete'):
            self.files[data['file_id']] = b''.join(self.parts[i] for i in sorted(self.parts))
            return {'file_id': data['file_id']}
        raise AssertionError(endpoint)

    def get(self, url, *, stream, timeout):
        assert stream is True
        data = self.files[url]
        source = io.BytesIO(data)
        response = Mock(headers={'Content-Length': str(len(data))})
        response.iter_content.side_effect = lambda n: iter(lambda: source.read(min(n, 27011)), b'')
        return response

    def put(self, url, *, data, headers, timeout):
        part = b''.join(iter(lambda: data.read(37007), b''))
        assert len(part) == int(headers['Content-Length'])
        self.parts[int(url)] = part
        return Mock(status_code=200)


class StorageStreamingMatrixTests(unittest.TestCase):
    def endpoints(self, payload):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / 'source').write_bytes(payload)
        local = LocalDriver({'root_path': root})

        ftp_peer = MemoryFtp(payload)
        ftp = FtpDriver({'host': 'matrix.invalid'})
        self.enterContext(patch.object(ftp, '_connect', lambda: nullcontext(ftp_peer)))

        sftp_peer = _FakeSftp()
        sftp_peer.nodes['/srv/source'] = {'kind': 'file', 'data': payload}
        sftp = SftpDriver(sftp_config())
        self.enterContext(patch.object(sftp, '_connect', lambda: nullcontext(sftp_peer)))

        smb_peer = MemorySmb()
        smb_peer.payload = payload
        self.enterContext(patch.dict('sys.modules', {'smbclient': smb_peer}))
        smb = SmbDriver({'host': 'server', 'share': 'share'})
        self.addCleanup(smb.close)

        cloud = MemoryAliyun(payload)
        self.addCleanup(cloud.driver.session.close)

        vault = root / 'vault'
        vault.mkdir()
        crypt = CryptDriver(local, '/vault', 'matrix fixture', True)
        crypt.upload('/source', io.BytesIO(payload), len(payload))

        def take_local():
            path = root / 'destination'
            data = path.read_bytes()
            path.unlink()
            return data

        def take_crypt():
            physical = vault / crypt.cipher.encode_name('destination', False)
            restored = io.BytesIO()
            crypt.download('/destination', restored)
            self.assertEqual(physical.stat().st_size, crypt.cipher.encrypted_size(restored.tell()))
            physical.unlink()
            return restored.getvalue()

        # Consume the committed object after each pair so a later silent no-op fails.
        return [
            (local, take_local), (ftp, lambda: ftp_peer.files.pop('/destination')),
            (sftp, lambda: sftp_peer.nodes.pop('/srv/destination')['data']),
            (smb, lambda: smb_peer.written.pop(r'\\server\share\destination')),
            (cloud.driver, lambda: cloud.files.pop('destination')),
            (crypt, take_crypt),
        ]

    def check_matrix(self, payload):
        endpoints = self.endpoints(payload)
        for source, _ in endpoints:
            for destination, take in endpoints:
                with self.subTest(source=source.driver_type, destination=destination.driver_type):
                    progress = []
                    stream_transfer(source, '/source', destination, '/destination', len(payload), progress.append)
                    self.assertEqual(take(), payload)
                    self.assertEqual(progress[-1], 1.0)

    def test_all_36_pairs_binary_payload(self):
        self.check_matrix(hashlib.shake_256(b'matrix').digest(1024 * 1024 + 997))

    def test_all_36_pairs_empty(self):
        self.check_matrix(b'')

    def test_new_sequential_driver_can_stream_into_each_destination(self):
        prefix = b'first' * 30000  # enough to fill more than one authenticated record
        payload = prefix + b'last'

        class NewDriver(StorageDriver):
            def list(self, path, details=False):
                return [{'name': 'source', 'is_dir': False, 'size': len(payload)}]

            def download(self, path, target, progress=None, cancel=None):
                target.write(prefix)
                if not consumed.wait(timeout=5):
                    raise AssertionError('destination required EOF before consuming the first bytes')
                target.write(b'last')

        for destination, take in self.endpoints(b''):
            with self.subTest(destination=destination.driver_type):
                consumed = threading.Event()
                stream_transfer(NewDriver(), '/source', destination, '/destination', len(payload),
                                progress=lambda value: consumed.set() if 0 < value < 1 else None)
                self.assertEqual(take(), payload)

    def test_each_source_can_feed_a_new_sequential_destination(self):
        class DigestSink(StorageDriver):
            def upload(self, path, source, size=None, progress=None, cancel=None):
                digest = hashlib.sha256()
                for chunk in iter(lambda: source.read(7919), b''):
                    digest.update(chunk)
                return digest.digest()

        data = hashlib.shake_256(b'sequential').digest(128 * 1024 + 19)
        expected = hashlib.sha256(data).digest()
        for source, _ in self.endpoints(data):
            with self.subTest(source=source.driver_type):
                actual = stream_transfer(source, '/source', DigestSink(), '/digest', len(data))
                self.assertEqual(actual, expected)

    def test_aliyun_part_replay_spills_only_above_32_mib_and_closes(self):
        mib = 1024 * 1024
        source = Mock()
        source.read.side_effect = lambda n: b'x' * n
        reader = _PartReader(source, 32 * mib + 1, None, lambda n: None)
        try:
            for _ in range(32):
                self.assertEqual(len(reader.read(mib)), mib)
            self.assertFalse(reader.buffer._rolled)
            self.assertEqual(reader.read(1), b'x')
            self.assertTrue(reader.buffer._rolled)
            reader.reset()
            source.read.side_effect = AssertionError('replay read the upstream source')
            self.assertEqual(reader.read(17), b'x' * 17)
        finally:
            reader.close()
        self.assertTrue(reader.buffer.closed)

@contextmanager
def sftp_loopback():
    """Real SSH handshake, pinned ephemeral key, password auth and SFTP packets."""
    fs = _FakeSftp()
    key = paramiko.ECDSAKey.generate()

    class Auth(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            if (username, password) == ('matrix', 'fixture'):
                return paramiko.AUTH_SUCCESSFUL
            return paramiko.AUTH_FAILED

        def check_channel_request(self, kind, chanid):
            if kind == 'session':
                return paramiko.OPEN_SUCCEEDED
            return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    class Files(paramiko.SFTPServerInterface):
        def lstat(self, path):
            try:
                entry = fs.lstat(path)
            except FileNotFoundError:
                return paramiko.SFTP_NO_SUCH_FILE
            attrs = paramiko.SFTPAttributes()
            attrs.st_mode, attrs.st_size = entry.st_mode, entry.st_size
            return attrs

        def open(self, path, flags, attr):
            handle = paramiko.SFTPHandle(flags)
            if flags & os.O_WRONLY:
                handle.writefile = fs.open(path, 'wbx')
            else:
                handle.readfile = fs.open(path, 'rb')
            return handle

        def posix_rename(self, oldpath, newpath):
            fs.posix_rename(oldpath, newpath)
            return paramiko.SFTP_OK

        def remove(self, path):
            try:
                fs.remove(path)
            except FileNotFoundError:
                return paramiko.SFTP_NO_SUCH_FILE
            return paramiko.SFTP_OK

    class Peer(socketserver.BaseRequestHandler):
        def handle(self):
            with paramiko.Transport(self.request) as transport:
                transport.add_server_key(key)
                transport.set_subsystem_handler('sftp', paramiko.SFTPServer, Files)
                transport.start_server(server=Auth())
                channel = transport.accept(timeout=8)
                if channel is not None:
                    transport.join(timeout=12)
                    channel.close()

    with socketserver.TCPServer(('127.0.0.1', 0), Peer) as server:
        worker = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
        worker.start()
        try:
            driver = SftpDriver(sftp_config(host='127.0.0.1', port=server.server_address[1],
                                            username='matrix', password='fixture', timeout=8,
                                            host_key_fingerprint=key.fingerprint))
            yield driver, fs
        finally:
            server.shutdown()
            worker.join()


class LoopbackStreamingTests(unittest.TestCase):
    def round_trip(self, peer, root):
        payload = hashlib.shake_256(b'over the wire').digest(1024 * 1024 + 313)
        (root / 'source').write_bytes(payload)
        with sftp_loopback() as (sftp, _):
            stream_transfer(peer, '/source', sftp, '/middle', len(payload))
            stream_transfer(sftp, '/middle', peer, '/restored', len(payload))
        self.assertEqual((root / 'restored').read_bytes(), payload)

    def test_local_sftp_over_loopback(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.round_trip(LocalDriver({'root_path': tmp}), Path(tmp))

    def test_crypt_backup_and_restore_over_loopback_sftp(self):
        marker = b'plaintext marker for the encrypted SFTP backup'
        data = marker + hashlib.shake_256(marker).digest(1024 * 1024)
        with tempfile.TemporaryDirectory() as tmp, sftp_loopback() as (sftp, peer):
            root = Path(tmp)
            (root / 'source').write_bytes(data)
            local = LocalDriver({'root_path': tmp})
            peer.mkdir('/srv/vault')
            crypt = CryptDriver(sftp, '/vault', 'network fixture', True)
            stream_transfer(local, '/source', crypt, '/backup.bin', len(data))

            # Inspect the server-side object independently, before any restore reads.
            physical = '/srv/vault/' + crypt.cipher.encode_name('backup.bin', False)
            self.assertEqual([p for p in peer.nodes if p.startswith('/srv/vault/')], [physical])
            self.assertNotEqual(physical, '/srv/vault/backup.bin')
            wire = peer.nodes[physical]['data']
            self.assertEqual(len(wire), crypt.cipher.encrypted_size(len(data)))
            self.assertNotIn(marker, wire)

            stream_transfer(crypt, '/backup.bin', local, '/restored', len(data))
            self.assertEqual((root / 'restored').read_bytes(), data)

    def test_ftp_sftp_over_loopback(self):
        try:
            from pyftpdlib.authorizers import DummyAuthorizer
            from pyftpdlib.handlers import FTPHandler
            from pyftpdlib.ioloop import IOLoop
            from pyftpdlib.servers import FTPServer
        except ModuleNotFoundError as exc:
            if exc.name != 'pyftpdlib':
                raise
            self.skipTest('optional loopback FTP server requires pyftpdlib')

        class Handler(FTPHandler):
            authorizer = DummyAuthorizer()

        # Avoid pyftpdlib's automatic process-wide logging reconfiguration.
        logger = logging.getLogger('pyftpdlib')
        handler = logging.NullHandler()
        logger.addHandler(handler)
        self.addCleanup(logger.removeHandler, handler)
        with tempfile.TemporaryDirectory() as tmp:
            Handler.authorizer.add_user('matrix', 'fixture', tmp, perm='elradfmw')
            server = FTPServer(('127.0.0.1', 0), Handler, ioloop=IOLoop())
            stop = threading.Event()

            def serve():
                while not stop.is_set():
                    server.ioloop.loop(timeout=0.05, blocking=False)

            worker = threading.Thread(target=serve, daemon=True)
            worker.start()
            try:
                ftp = FtpDriver({'host': '127.0.0.1', 'port': server.address[1],
                                 'username': 'matrix', 'password': 'fixture', 'timeout': 8})
                self.round_trip(ftp, Path(tmp))
            finally:
                stop.set()
                worker.join()
                server.close_all()
