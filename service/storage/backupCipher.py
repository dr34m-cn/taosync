"""TaoSync backup codec v1. All sizes are bytes.

Names are single UTF-8 components encoded as ``tsb-1-`` + unpadded base32
of AES-SIV ciphertext. Equal names under one passphrase are intentionally
linkable across directories, file types and backups. No Unicode normalization.

File layout: magic/version | 32-byte random salt | AES-GCM records. All but
the final record carry 64 KiB of plaintext; the final record carries 1..64 KiB
(0 only for an empty file). The header is associated data. A per-file HKDF key
and 96-bit big-endian nonce (2 * record index + final flag) bind each record
to its file, position and finality. No unauthenticated length fields.
"""

import base64
import binascii
import os
from operator import index

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, AESSIV
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .drivers.base import check_cancel


class ForeignBackupName(ValueError):
    """The physical component is outside the reserved 'tsb-' namespace."""


class InvalidBackupName(ValueError):
    """A reserved name is malformed, unsupported or unauthenticated."""


class InvalidBackupData(ValueError):
    """The encrypted stream is malformed, incomplete or unauthenticated."""


_PREFIX = 'tsb-1-'
_NAME_AAD = b'TaoSync backup name v1'
_MAGIC = b'TSBK\x01'
_SALT = 32
_HEADER = len(_MAGIC) + _SALT
_TAG = 16
_CHUNK = 64 * 1024
_RECORD = _CHUNK + _TAG
_MAX_RECORDS = 1 << 32


def encrypted_size(n):
    """Exact wire length for n plaintext bytes, or None for unknown size."""
    if n is None:
        return None
    n = index(n)
    if not 0 <= n <= _MAX_RECORDS * _CHUNK:
        raise ValueError('plaintext size outside v1 limits')
    records = max(1, (n + _CHUNK - 1) // _CHUNK)
    return _HEADER + n + records * _TAG


def decrypted_size(n):
    """Infer (but do not authenticate) plaintext length; reject impossible sizes."""
    if n is None:
        return None
    body = index(n) - _HEADER
    if body == _TAG:
        return 0
    full, tail = divmod(body, _RECORD)
    if body < _TAG or (0 < tail <= _TAG) or full + bool(tail) > _MAX_RECORDS:
        raise InvalidBackupData('invalid ciphertext size')
    return full * _CHUNK + max(0, tail - _TAG)


def _component(name):
    if (not name or name in ('.', '..') or '/' in name or '\\' in name
            or any(ord(c) < 32 for c in name)):
        raise InvalidBackupName('invalid logical name component')
    return name


def _base32(data):
    return base64.b32encode(data).rstrip(b'=').decode('ascii').lower()


def _file_cipher(key, header):
    file_key = HKDF(hashes.SHA256(), 32, header[len(_MAGIC):], b'TaoSync backup file v1').derive(key)
    return AESGCM(file_key)


def _nonce(number, final):
    if number >= _MAX_RECORDS or (number == _MAX_RECORDS - 1 and not final):
        raise InvalidBackupData('too many records')
    return (2 * number + final).to_bytes(12, 'big')


class BackupCipher:
    """Reusable keys for one backup passphrase. Streams do not own their I/O."""

    encrypted_size = staticmethod(encrypted_size)
    decrypted_size = staticmethod(decrypted_size)

    def __init__(self, passphrase):
        if isinstance(passphrase, str):
            passphrase = passphrase.encode('utf-8')
        if not isinstance(passphrase, bytes) or not passphrase:
            raise ValueError('a non-empty passphrase is required')
        # The fixed v1 domain salt makes names portable without a vault header.
        # Split the KDF output into independent name and file root keys.
        keys = Scrypt(salt=b'TaoSync backup passphrase v1', length=96,
                      n=2**17, r=8, p=1).derive(passphrase)
        self._names = AESSIV(keys[:64])
        self._files = keys[64:]

    def encode_name(self, name, is_dir):
        """Encode a component; file and directory names share one namespace."""
        raw = _component(name).encode('utf-8')
        if len(_PREFIX) + ((len(raw) + _TAG) * 8 + 4) // 5 > 255:
            raise InvalidBackupName('encoded component exceeds 255 bytes')
        return _PREFIX + _base32(self._names.encrypt(raw, [_NAME_AAD]))

    def decode_name(self, physical, is_dir):
        """Accept ASCII case variations, never return a foreign name as cleartext."""
        if physical[:4].lower() != 'tsb-':
            raise ForeignBackupName('not a backup name')
        if len(physical) > 255 or not physical.isascii() or not physical.lower().startswith(_PREFIX):
            raise InvalidBackupName('invalid or unsupported backup name')
        token = physical[len(_PREFIX):].lower()
        try:
            raw = base64.b32decode(token.upper() + '=' * (-len(token) % 8))
            if len(raw) <= _TAG or _base32(raw) != token:
                raise InvalidBackupName('noncanonical backup name')
            return _component(self._names.decrypt(raw, [_NAME_AAD]).decode('utf-8'))
        except (binascii.Error, InvalidTag, UnicodeError) as exc:
            raise InvalidBackupName('invalid or unauthenticated backup name') from exc

    def encrypt_reader(self, source, plaintext_size=None, cancel=None):
        """Return a read-only ciphertext source. Even read() returns at most 64 KiB.

        Loop to EOF. A declared size must match the actual source, including EOF.
        """
        encrypted_size(plaintext_size)
        return _Reader(self._records(source, plaintext_size, cancel), cancel)

    def _records(self, source, remaining, cancel):
        header = _MAGIC + os.urandom(_SALT)
        cipher = _file_cipher(self._files, header)
        yield header
        number = 0
        block = bytearray()
        while True:
            # One byte of lookahead distinguishes a full final block even for a
            # pipe of unknown length. A short nonempty read does not mean EOF.
            check_cancel(cancel)
            want = _CHUNK + 1 - len(block)
            if remaining is not None:
                want = min(want, remaining + 1)
            data = source.read(want)
            check_cancel(cancel)
            if data is None or len(data) > want:
                raise OSError('expected a blocking bounded binary source')
            if remaining is not None:
                remaining -= len(data)
                if remaining < 0 or (not data and remaining):
                    raise ValueError('source length differs from plaintext_size')
            if not data:
                yield cipher.encrypt(_nonce(number, True), block, header)
                return
            block.extend(data)
            if len(block) > _CHUNK:
                yield cipher.encrypt(_nonce(number, False), memoryview(block)[:_CHUNK], header)
                number += 1
                block = block[_CHUNK:]

    def decrypt_writer(self, target, cancel=None):
        """Write ciphertext fragments, then call finish() ONLY on upstream success.

        Earlier authenticated records can reach the target before finish(). Use
        a staging target and discard it on any error. For every nonempty file,
        the last plaintext record is released only by a successful EOF check.
        """
        return _Writer(self._files, target, cancel)


class _Reader:
    allow_rapid_upload = False

    def __init__(self, records, cancel):
        self._records = records
        self._cancel = cancel
        self._pending = memoryview(b'')
        self._failed = False

    def read(self, size=-1):
        if self._failed:
            raise ValueError('ciphertext reader has failed')
        limit = _CHUNK if size is None or size < 0 else min(_CHUNK, index(size))
        out = bytearray()
        try:
            check_cancel(self._cancel)
            while len(out) < limit:
                if not self._pending:
                    record = next(self._records, None)
                    if record is None:
                        break
                    self._pending = memoryview(record)
                take = min(len(self._pending), limit - len(out))
                out.extend(self._pending[:take])
                self._pending = self._pending[take:]
        except Exception:
            self._failed = True
            raise
        return bytes(out)


class _Writer:
    def __init__(self, key, target, cancel):
        self._key = key
        self._target = target
        self._cancel = cancel
        self._cipher = None
        self._header = None
        self._buffer = bytearray()
        self._number = 0
        self._closed = False

    def _release(self, final):
        if len(self._buffer) < _TAG or (self._number and len(self._buffer) == _TAG):
            raise InvalidBackupData('missing final record')
        try:
            data = self._cipher.decrypt(_nonce(self._number, final), self._buffer, self._header)
        except InvalidTag as exc:
            raise InvalidBackupData('record authentication failed') from exc
        view = memoryview(data)
        while view:
            check_cancel(self._cancel)
            n = self._target.write(view)
            if n is None or not 0 < n <= len(view):
                raise OSError('target did not accept plaintext')
            view = view[n:]
        self._buffer.clear()
        self._number += 1

    def write(self, data):
        if self._closed:
            raise ValueError('ciphertext writer is no longer active')
        try:
            check_cancel(self._cancel)
            view = memoryview(data).cast('B')
            size = len(view)
            while view:
                check_cancel(self._cancel)
                if self._cipher is not None and len(self._buffer) == _RECORD:
                    # Only the presence of another byte rules out a final record.
                    self._release(False)
                limit = _HEADER if self._cipher is None else _RECORD
                take = min(limit - len(self._buffer), len(view))
                self._buffer.extend(view[:take])
                view = view[take:]
                if self._cipher is None and len(self._buffer) == _HEADER:
                    self._header = bytes(self._buffer)
                    if not self._header.startswith(_MAGIC):
                        raise InvalidBackupData('invalid or unsupported backup header')
                    self._cipher = _file_cipher(self._key, self._header)
                    self._buffer.clear()
            return size
        except Exception:
            self._closed = True
            raise

    def finish(self):
        if self._closed:
            raise ValueError('ciphertext writer is no longer active')
        self._closed = True
        check_cancel(self._cancel)
        if self._cipher is None:
            raise InvalidBackupData('incomplete backup header')
        self._release(True)
