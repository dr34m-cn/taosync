import asyncio
import os
import socket
import ssl
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from tornado.web import Application, RequestHandler

from service.system.httpsListener import HttpsError, HttpsListener


def pair():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, 'localhost')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1)).sign(key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM).decode(),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption()).decode())


class Page(RequestHandler):
    def get(self):
        self.write('business page')


class HttpsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.path = self.folder / 'https.pem'
        self.app = Application([(r'/', Page)])
        self.listener = HttpsListener(self.app, self.path, port=0, address='127.0.0.1')

    async def asyncTearDown(self):
        if self.listener.server:
            self.listener.server.stop()
            await self.listener.server.close_all_connections()

    async def check_peer(self, cert):
        port = next(iter(self.listener.server._sockets.values())).getsockname()[1]
        ctx = ssl.create_default_context(cadata=cert)
        reader, writer = await asyncio.open_connection('127.0.0.1', port, ssl=ctx, server_hostname='localhost')
        try:
            self.assertEqual(writer.get_extra_info('ssl_object').getpeercert(True), ssl.PEM_cert_to_DER_cert(cert))
            writer.write(b'GET / HTTP/1.0\r\nHost: localhost\r\n\r\n')
            self.assertIn(b'business page', await reader.read())
        finally:
            writer.close()
            await writer.wait_closed()

    async def test_enable_replace_restore_and_disable(self):
        first, second = pair(), pair()
        self.listener.restore()
        self.assertFalse(self.listener.status()['enabled'])
        self.listener.apply(True, *first)
        if os.name == 'posix':
            self.assertEqual(self.path.stat().st_mode & 0o077, 0)
        await self.check_peer(first[0])
        saved = self.path.read_bytes()
        with self.assertRaisesRegex(HttpsError, 'https_invalid_pair'):
            self.listener.apply(True, second[0], first[1])
        self.assertEqual(self.path.read_bytes(), saved)
        await self.check_peer(first[0])
        self.listener.apply(True, *second)
        await self.check_peer(second[0])
        self.listener.server.stop()
        await self.listener.server.close_all_connections()
        self.listener = HttpsListener(self.app, self.path, port=0, address='127.0.0.1')
        self.listener.restore()
        await self.check_peer(second[0])
        active = self.path.read_bytes()
        self.listener.apply(False)
        self.listener = HttpsListener(self.app, self.path, port=0, address='127.0.0.1')
        self.listener.restore()
        self.assertEqual(self.listener.status(), {'enabled': False, 'configured': True, 'autoStart': False, 'port': 0})
        self.listener.apply(True)
        self.assertEqual(self.path.read_bytes(), active)
        await self.check_peer(second[0])
        self.assertFalse(self.listener.clear()['enabled'])
        self.assertEqual(list(self.folder.iterdir()), [])
        self.listener.restore()
        self.assertFalse(self.listener.status()['configured'])

    async def test_legacy_pem_restores_and_retained_pair_can_be_replaced_or_cleared(self):
        cert, key = pair()
        self.path.write_bytes((cert + key).encode('ascii'))
        self.listener.restore()
        await self.check_peer(cert)
        self.listener.apply(False)
        replacement = pair()
        self.listener.apply(True, *replacement)
        await self.check_peer(replacement[0])
        self.listener.apply(False)
        self.listener.clear()
        self.listener.restore()
        self.assertFalse(self.listener.status()['configured'])
        with self.assertRaisesRegex(HttpsError, 'https_invalid_pair'):
            self.listener.apply(True)
        self.assertEqual(list(self.folder.iterdir()), [])

    async def test_failed_disable_clear_or_reenable_preserves_committed_state(self):
        cert, key = pair()
        self.listener.apply(True, cert, key)
        with mock.patch('service.system.httpsListener.os.replace', side_effect=OSError), self.assertRaisesRegex(HttpsError, 'storage_error'):
            self.listener.apply(False)
        with mock.patch.object(Path, 'unlink', side_effect=OSError), self.assertRaisesRegex(HttpsError, 'storage_error'):
            self.listener.clear()
        self.assertTrue(self.listener.status()['autoStart'])
        await self.check_peer(cert)
        self.listener.apply(False)
        retained = self.path.read_bytes()
        with mock.patch.object(self.app, 'listen', side_effect=OSError), self.assertRaisesRegex(HttpsError, 'port_unavailable'):
            self.listener.apply(True)
        self.assertEqual(self.path.read_bytes(), retained)
        self.assertFalse(self.listener.status()['enabled'])
        self.assertFalse(self.listener.status()['autoStart'])
        self.listener.apply(True)
        await self.check_peer(cert)

    async def test_port_validation_switch_and_restore(self):
        self.listener.http_port = 8023
        cert, key = pair()
        self.listener.apply(True, cert, key)
        previous = self.listener.server
        for invalid in (8023, 8024, -1, 65536, True, 4.5, '9999'):
            with self.assertRaisesRegex(HttpsError, 'invalid_port'):
                self.listener.apply(True, port=invalid)
            self.assertIs(self.listener.server, previous)
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            port = reserved.getsockname()[1]
            reserved.listen()
            with self.assertRaisesRegex(HttpsError, 'port_unavailable'):
                self.listener.apply(True, port=port)
            self.assertIs(self.listener.server, previous)
        self.listener.apply(True, port=port)
        self.assertIsNot(self.listener.server, previous)
        self.assertEqual(self.listener.status()['port'], port)
        await self.check_peer(cert)
        self.listener.stop()
        self.listener = HttpsListener(self.app, self.path, address='127.0.0.1', http_port=8023)
        self.listener.restore()
        self.assertEqual(self.listener.status()['port'], port)
        await self.check_peer(cert)
        self.listener.clear()
        self.assertEqual(self.listener.status()['port'], port)
        self.assertFalse(self.listener.status()['configured'])

    async def test_bind_and_commit_failures_leave_no_config(self):
        cert, key = pair()
        with mock.patch.object(self.app, 'listen', side_effect=OSError), self.assertRaisesRegex(HttpsError, 'port_unavailable'):
            self.listener.apply(True, cert, key)
        with mock.patch('service.system.httpsListener.os.replace', side_effect=OSError), self.assertRaisesRegex(HttpsError, 'storage_error'):
            self.listener.apply(True, cert, key)
        self.assertFalse(self.listener.status()['enabled'])
        self.assertEqual(list(self.folder.iterdir()), [])
