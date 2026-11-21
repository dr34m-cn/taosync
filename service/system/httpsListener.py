import logging
import os
import ssl
import tempfile
from pathlib import Path

from tornado.ioloop import IOLoop

from common.LNG import G


# Keep the startup choice and key pair in one atomic file. Legacy PEMs have no header.
DISABLED_HEADER = b'# TaoSync: HTTPS disabled\n'
PORT_HEADER = b'# TaoSync: HTTPS port '


class HttpsError(ValueError):
    """A locale key, never uploaded key material."""


class HttpsListener:
    """All changes run on the business application's I/O loop."""

    def __init__(self, app, path=Path('data/https.pem'), port=8025, address=None, http_port=None):
        self.app = app
        self.path = path
        self.default_port = port
        self.http_port = http_port
        self.active_port = None
        self.address = address
        self.server = None

    def read_config(self):
        try:
            pem = self.path.read_bytes()
        except FileNotFoundError:
            pem = b''
        except OSError:
            raise HttpsError('https_storage_error') from None
        port = self.default_port
        if pem.startswith(PORT_HEADER):
            line, _, pem = pem.partition(b'\n')
            try:
                port = int(line[len(PORT_HEADER):])
            except ValueError:
                raise HttpsError('https_invalid_port') from None
        enabled = bool(pem) and not pem.startswith(DISABLED_HEADER)
        return port, enabled, pem.removeprefix(DISABLED_HEADER)

    def validate_port(self, port):
        if (type(port) is not int or not 1 <= port <= 65535 or port in (8024, self.http_port)):
            raise HttpsError('https_invalid_port')

    def status(self):
        port, enabled, pem = self.read_config()
        result = {'enabled': self.server is not None, 'configured': bool(pem), 'autoStart': enabled, 'port': port}
        if self.http_port is not None:
            result['httpPort'] = self.http_port
        return result

    @staticmethod
    def context(path):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            # Never prompt on stdin for an encrypted private key.
            ctx.load_cert_chain(path, password=lambda: b'')
        except (ssl.SSLError, ValueError):
            raise HttpsError('https_invalid_pair') from None
        return ctx

    def listen(self, ctx, port):
        try:
            return self.app.listen(port, address=self.address, ssl_options=ctx)
        except OSError:
            raise HttpsError('https_port_unavailable') from None

    def restore(self):
        try:
            port, enabled, _ = self.read_config()
            if enabled:
                if port != 0 or self.default_port != 0:
                    self.validate_port(port)
                self.server = self.listen(self.context(self.path), port)
                self.active_port = port
        except (HttpsError, OSError) as exc:
            logging.getLogger(__name__).error(G(str(exc) if isinstance(exc, HttpsError) else 'https_storage_error'))

    def stop(self):
        if self.server:
            self.server.stop()
            # Allow a settings response sent over HTTPS to finish first.
            IOLoop.current().add_callback(self.server.close_all_connections)
            self.server = None

    def clear(self):
        port, _, _ = self.read_config()
        try:
            if port == self.default_port:
                self.path.unlink(missing_ok=True)
            else:
                self.commit(b'', enable=False, port=port)
        except OSError:
            raise HttpsError('https_storage_error') from None
        self.stop()
        return self.status()

    def apply(self, enabled, cert=None, key=None, port=None):
        if not isinstance(enabled, bool):
            raise HttpsError('https_invalid_pair')
        saved_port, saved_enabled, pem = self.read_config()
        if port is None:
            port = saved_port
        if port != 0 or self.default_port != 0:
            self.validate_port(port)
        if enabled and (cert is not None or key is not None):
            if not all(isinstance(s, str) and s.isascii() and len(s) <= 256 * 1024 for s in (cert, key)):
                raise HttpsError('https_invalid_pair')
            if not cert.strip().startswith('-----BEGIN CERTIFICATE-----') or 'PRIVATE KEY' in cert or 'CERTIFICATE' in key:
                raise HttpsError('https_invalid_pair')
            pem = (cert.strip() + '\n' + key.strip() + '\n').encode('ascii')
        elif enabled and not pem:
            raise HttpsError('https_invalid_pair')
        elif enabled == saved_enabled == (self.server is not None) and port == saved_port:
            return self.status()
        try:
            self.commit(pem, enable=enabled, port=port)
            if not enabled:
                self.stop()
        except OSError:
            raise HttpsError('https_storage_error') from None
        return self.status()

    def commit(self, pem, *, enable, port):
        if not enable and pem:
            pem = DISABLED_HEADER + pem
        if port != self.default_port:
            pem = PORT_HEADER + str(port).encode('ascii') + b'\n' + pem
        upload = tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False)
        staged = Path(upload.name)
        new_server = None
        try:
            with upload:
                upload.write(pem)
            if enable:
                ctx = self.context(staged)
                if not self.server or port != self.active_port:
                    new_server = self.listen(ctx, port)
            os.replace(staged, self.path)
            if new_server:
                self.stop()
                self.server = new_server
                self.active_port = port
            elif enable:
                # Tornado uses ssl_options for each newly accepted connection.
                self.server.ssl_options = ctx
        finally:
            if new_server and self.server is not new_server:
                new_server.stop()
            staged.unlink(missing_ok=True)
