import logging
import os
import ssl
import tempfile
from pathlib import Path

from tornado.ioloop import IOLoop

from common.LNG import G


# Keep the startup choice and key pair in one atomic file. Legacy PEMs have no header.
DISABLED_HEADER = b'# TaoSync: HTTPS disabled\n'


class HttpsError(ValueError):
    """A locale key, never uploaded key material."""


class HttpsListener:
    """All changes run on the business application's I/O loop."""

    def __init__(self, app, path=Path('data/https.pem'), port=8025, address=None):
        self.app = app
        self.path = path
        self.port = port
        self.address = address
        self.server = None

    def saved_enabled(self):
        try:
            with self.path.open('rb') as pem:
                return pem.read(len(DISABLED_HEADER)) != DISABLED_HEADER
        except FileNotFoundError:
            return None
        except OSError:
            raise HttpsError('https_storage_error') from None

    def status(self):
        saved = self.saved_enabled()
        return {'enabled': self.server is not None, 'configured': saved is not None,
                'autoStart': saved is True, 'port': self.port}

    @staticmethod
    def context(path):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            # Never prompt on stdin for an encrypted private key.
            ctx.load_cert_chain(path, password=lambda: b'')
        except (ssl.SSLError, ValueError):
            raise HttpsError('https_invalid_pair') from None
        return ctx

    def listen(self, ctx):
        try:
            return self.app.listen(self.port, address=self.address, ssl_options=ctx)
        except OSError:
            raise HttpsError('https_port_unavailable') from None

    def restore(self):
        try:
            if self.saved_enabled():
                self.server = self.listen(self.context(self.path))
        except (HttpsError, OSError) as exc:
            logging.getLogger(__name__).error(G(str(exc) if isinstance(exc, HttpsError) else 'https_storage_error'))

    def stop(self):
        if self.server:
            self.server.stop()
            # Allow a settings response sent over HTTPS to finish first.
            IOLoop.current().add_callback(self.server.close_all_connections)
            self.server = None

    def clear(self):
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            raise HttpsError('https_storage_error') from None
        self.stop()
        return self.status()

    def apply(self, enabled, cert=None, key=None):
        if not isinstance(enabled, bool):
            raise HttpsError('https_invalid_pair')
        try:
            if not enabled:
                if self.saved_enabled():
                    self.commit(DISABLED_HEADER + self.path.read_bytes(), enable=False)
                self.stop()
            elif cert is None and key is None:
                saved = self.saved_enabled()
                if saved is None:
                    raise HttpsError('https_invalid_pair')
                if not saved:
                    self.commit(self.path.read_bytes().removeprefix(DISABLED_HEADER), enable=True)
                elif not self.server:
                    self.server = self.listen(self.context(self.path))
            else:
                self.install(cert, key)
        except OSError:
            raise HttpsError('https_storage_error') from None
        return self.status()

    def install(self, cert, key):
        if not all(isinstance(s, str) and s.isascii() and len(s) <= 256 * 1024 for s in (cert, key)):
            raise HttpsError('https_invalid_pair')
        if not cert.strip().startswith('-----BEGIN CERTIFICATE-----') or 'PRIVATE KEY' in cert or 'CERTIFICATE' in key:
            raise HttpsError('https_invalid_pair')
        self.commit((cert.strip() + '\n' + key.strip() + '\n').encode('ascii'), enable=True)

    def commit(self, pem, *, enable):
        upload = tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False)
        staged = Path(upload.name)
        new_server = None
        try:
            with upload:
                upload.write(pem)
            if enable:
                ctx = self.context(staged)
                if not self.server:
                    new_server = self.listen(ctx)
            os.replace(staged, self.path)
            if new_server:
                self.server = new_server
            elif enable:
                # Tornado uses ssl_options for each newly accepted connection.
                self.server.ssl_options = ctx
        finally:
            if new_server and self.server is not new_server:
                new_server.stop()
            staged.unlink(missing_ok=True)
