import io
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, AESSIV
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from service.storage import backupCipher
from service.storage.backupCipher import (
    BackupCipher, ForeignBackupName, InvalidBackupData, InvalidBackupName,
    _CompatAESSIV, decrypted_size, encrypted_size,
)
from service.storage.drivers.base import TransferCancelled


# V1 constants, intentionally not imported: changing the format breaks old backups.
CHUNK = 65536
HEADER = 37
RECORD = CHUNK + 16


def drain(reader):
    return b''.join(iter(reader.read, b''))


def flip(data, offset):
    damaged = bytearray(data)
    damaged[offset] ^= 1
    return damaged


class ShortSource(io.BytesIO):
    metadata = {'sha1': 'plaintext hash'}
    can_read_range = allow_rapid_upload = True

    def read_range(self, *args):
        raise AssertionError('must only read sequentially')

    def read(self, size=-1):
        if not 0 < size <= CHUNK + 1:
            raise AssertionError(f'unbounded source read: {size}')
        return super().read(min(size, 211))


class BackupCipherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cipher = BackupCipher('codec tests')

    def encrypt(self, data):
        return drain(self.cipher.encrypt_reader(io.BytesIO(data), len(data)))

    def test_v1_known_answers(self):
        name = 'tsb-1-j7dfhi4icyrbhlvv7dzcurwhqe2w3h3l3znbhgwnvk6q'
        self.assertEqual(self.cipher.encode_name('example.txt', False), name)
        self.assertEqual(self.cipher.decode_name(name, True), 'example.txt')
        salt = bytes(range(32))
        for data, body in [(b'', '86f5dabed0d9087ce3c75732cecebcf7'),
                           (b'abc', 'f47a3298f08090a4a547e7de21952dc4a20b91')]:
            wire = b'TSBK\x01' + salt + bytes.fromhex(body)
            with patch('service.storage.backupCipher.os.urandom', return_value=salt):
                self.assertEqual(self.encrypt(data), wire)
            target = io.BytesIO()
            writer = self.cipher.decrypt_writer(target)
            writer.write(wire)
            writer.finish()
            self.assertEqual(target.getvalue(), data)

    def test_names_round_trip_without_case_or_normalization_collisions(self):
        names = ['a', 'A', 'CON', 'name. ', '\u96ea\U0001f642', '\xe9', 'e\u0301', 'a' * 139]
        physical = set()
        for name in names:
            token = self.cipher.encode_name(name, False)
            self.assertRegex(token, r'^tsb-1-[a-z2-7]+$')
            self.assertLessEqual(len(token), 255)
            self.assertEqual(self.cipher.encode_name(name, True), token)
            self.assertEqual(self.cipher.decode_name(token.upper(), False), name)
            self.assertNotIn(token.casefold(), physical)
            physical.add(token.casefold())
        for invalid in ['', '.', '..', 'a/b', 'a\\b', 'a\0b', 'line\nbreak', 'a' * 140]:
            with self.subTest(name=invalid), self.assertRaises(InvalidBackupName):
                self.cipher.encode_name(invalid, False)

    def test_name_errors_distinguish_foreign_entries_from_damaged_backups(self):
        for name in ('', 'hello', '.taosync-staging.part'):
            with self.assertRaises(ForeignBackupName):
                self.cipher.decode_name(name, False)
        valid = self.cipher.encode_name('a', False)
        alphabet = 'abcdefghijklmnopqrstuvwxyz234567'
        # 17 bytes in base32 have four unused low bits in the last character.
        alias = valid[:-1] + alphabet[alphabet.index(valid[-1]) ^ 1]
        for bad in ('tsb-', 'TSB-9-abc', 'tsb-1-!', 'tsb-1-a', 'tsb-1-\u212a',
                    valid + '=', valid + 'a' * 255, alias,
                    valid[:6] + ('a' if valid[6] != 'a' else 'b') + valid[7:]):
            with self.subTest(name=bad), self.assertRaises(InvalidBackupName):
                self.cipher.decode_name(bad, True)

    def test_wrong_passphrase_rejects_names_and_files_including_empty(self):
        wrong = BackupCipher(b'another passphrase')
        with self.assertRaises(InvalidBackupName):
            wrong.decode_name(self.cipher.encode_name('a', False), False)
        for data in (b'', b'x', b'x' * (CHUNK + 1)):
            target = io.BytesIO()
            writer = wrong.decrypt_writer(target)
            with self.assertRaises(InvalidBackupData):
                writer.write(self.encrypt(data))
                writer.finish()
            self.assertEqual(target.getvalue(), b'')
        for invalid in (None, b'', ''):
            with self.assertRaises(ValueError):
                BackupCipher(invalid)

    def test_final_chunk_is_never_released_by_write(self):
        for size in (0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 2 * CHUNK, 2 * CHUNK + 3):
            data = (bytes(range(256)) * (size // 256 + 1))[:size]
            for declared in (None, size):
                with self.subTest(size=size, declared=declared):
                    source = ShortSource(data)
                    reader = self.cipher.encrypt_reader(source, declared)
                    wire = drain(reader)
                    self.assertEqual(reader.read(), b'')
                    self.assertEqual(len(wire), self.cipher.encrypted_size(size))
                    self.assertEqual(self.cipher.decrypted_size(len(wire)), size)
                    target = io.BytesIO()
                    writer = self.cipher.decrypt_writer(target)
                    for i in range(0, len(wire), 503):
                        part = wire[i:i + 503]
                        self.assertEqual(writer.write(part), len(part))
                    self.assertEqual(writer.write(b''), 0)
                    # A late physical download failure means no finish() call.
                    before_finish = max(0, (size - 1) // CHUNK) * CHUNK
                    self.assertEqual(target.getvalue(), data[:before_finish])
                    writer.finish()
                    self.assertEqual(target.getvalue(), data)
                    with self.assertRaises(ValueError):
                        writer.finish()
                    with self.assertRaises(ValueError):
                        writer.write(b'x')
                    self.assertFalse(source.closed)

    def test_reader_is_bounded_lazy_and_opaque_to_rapid_upload(self):
        source = ShortSource(b'x' * (CHUNK * 6))
        reader = self.cipher.encrypt_reader(source)
        self.assertIs(reader.allow_rapid_upload, False)
        for attr in ('metadata', 'sha1', 'can_read_range', 'read_range', 'source', 'seek', 'tell', 'fileno'):
            self.assertFalse(hasattr(reader, attr), attr)
        self.assertEqual(reader.read(0), b'')
        self.assertEqual(source.tell(), 0)
        self.assertEqual(len(reader.read(1)), 1)
        self.assertEqual(source.tell(), 0)
        for size in (-1, 2**50, None):
            before = source.tell()
            self.assertEqual(len(reader.read(size)), CHUNK)
            self.assertLessEqual(source.tell() - before, CHUNK + 1)

    def test_declared_length_rejects_extra_or_missing_plaintext_before_final_record(self):
        for actual, declared in ((0, 1), (1, 0), (CHUNK, CHUNK + 1), (CHUNK + 1, CHUNK)):
            reader = self.cipher.encrypt_reader(ShortSource(b'x' * actual), declared)
            with self.subTest(actual=actual), self.assertRaises(ValueError):
                drain(reader)
            with self.assertRaises(ValueError):
                reader.read()

    def test_size_limits_and_impossible_ciphertext_lengths(self):
        self.assertIsNone(encrypted_size(None))
        self.assertIsNone(decrypted_size(None))
        maximum = CHUNK * 2**32
        for size in (0, CHUNK, CHUNK + 1, 10**12, maximum):
            self.assertEqual(decrypted_size(encrypted_size(size)), size)
        for size in (-1, maximum + 1):
            with self.assertRaises(ValueError):
                encrypted_size(size)
        for bad in [-1, 0, encrypted_size(0) - 1, encrypted_size(maximum) + 17,
                    *(encrypted_size(CHUNK) + gap for gap in range(1, 17))]:
            with self.subTest(size=bad), self.assertRaises(InvalidBackupData):
                decrypted_size(bad)

    def test_random_file_keys_and_every_form_of_record_damage(self):
        data = b'a' * CHUNK + b'b' * CHUNK + b'final'
        wire = self.encrypt(data)
        other = self.encrypt(data)
        self.assertNotEqual(wire[:HEADER], other[:HEADER])
        self.assertNotEqual(wire[HEADER:], other[HEADER:])
        h, a, b, end = (wire[:HEADER], wire[HEADER:HEADER + RECORD],
                        wire[HEADER + RECORD:HEADER + 2 * RECORD], wire[HEADER + 2 * RECORD:])
        cases = {
            'magic': flip(wire, 0), 'version': flip(wire, 4), 'salt': flip(wire, 5),
            'payload': flip(wire, HEADER), 'tag': flip(wire, HEADER + RECORD - 1),
            'final tag': flip(wire, -1), 'truncated tag': wire[:-1], 'no final': h + a + b,
            'swap': h + b + a + end, 'drop': h + a + end, 'duplicate': h + a + a + b + end,
            'spliced final': h + a + b + other[-len(end):], 'appended byte': wire + b'!',
            'appended file': wire + other, 'appended to full final': self.encrypt(data[:CHUNK]) + b'!',
        }
        for name, damaged in cases.items():
            with self.subTest(name=name):
                target = io.BytesIO()
                writer = self.cipher.decrypt_writer(target)
                with self.assertRaises(InvalidBackupData):
                    writer.write(damaged)
                    writer.finish()
                self.assertLess(target.tell(), CHUNK if name == 'appended to full final' else len(data))
                self.assertTrue(data.startswith(target.getvalue()))
                with self.assertRaises(ValueError):
                    writer.finish()

    def test_empty_file_requires_the_complete_authenticated_final_record(self):
        wire = self.encrypt(b'')
        for damaged in [*(wire[:i] for i in range(len(wire))), flip(wire, -1), wire + b'!']:
            target = Mock()
            writer = self.cipher.decrypt_writer(target)
            with self.assertRaises(InvalidBackupData):
                for byte in damaged:
                    writer.write(bytes([byte]))
                writer.finish()
            target.write.assert_not_called()

    def test_short_writes_and_target_errors(self):
        class ShortTarget(io.BytesIO):
            def write(self, data):
                return super().write(data[:53])

        data = b'x' * (CHUNK + 99)
        wire = self.encrypt(data)
        target = ShortTarget()
        writer = self.cipher.decrypt_writer(target)
        self.assertEqual(writer.write(wire), len(wire))
        writer.finish()
        self.assertEqual(target.getvalue(), data)
        for result in (0, None, OSError('disk full')):
            target = Mock()
            target.write.side_effect = [result]
            writer = self.cipher.decrypt_writer(target)
            with self.assertRaises(OSError):
                writer.write(wire)
            with self.assertRaises(ValueError):
                writer.finish()

    def test_cancel_during_short_read_and_before_finish(self):
        cancel = threading.Event()

        def interrupt(size):
            cancel.set()
            return b'x'

        source = Mock()
        source.read.side_effect = interrupt
        reader = self.cipher.encrypt_reader(source, None, cancel)
        with self.assertRaises(TransferCancelled):
            reader.read()
        self.assertEqual(source.read.call_count, 1)
        cancel.clear()
        target = io.BytesIO()
        writer = self.cipher.decrypt_writer(target, cancel)
        writer.write(self.encrypt(b'x' * CHUNK))
        cancel.set()
        with self.assertRaises(TransferCancelled):
            writer.finish()
        self.assertEqual(target.getvalue(), b'')
        cancel.clear()
        with self.assertRaises(ValueError):
            writer.finish()

    def test_compat_aes_siv_matches_rfc5297_and_native_aessiv(self):
        # RFC 5297 Appendix A.1 (deterministic authenticated encryption)
        key_a1 = bytes.fromhex(
            'fffefdfcfbfaf9f8f7f6f5f4f3f2f1f0'
            'f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff'
        )
        aad_a1 = [bytes.fromhex(
            '101112131415161718191a1b1c1d1e1f'
            '2021222324252627'
        )]
        pt_a1 = bytes.fromhex('112233445566778899aabbccddee')
        ct_a1 = bytes.fromhex(
            '85632d07c6e8f37f950acd320a2ecc93'
            '40c02b9690c4dc04daef7f6afe5c'
        )
        compat_a1 = _CompatAESSIV(key_a1)
        self.assertEqual(compat_a1.encrypt(pt_a1, aad_a1), ct_a1)
        self.assertEqual(compat_a1.decrypt(ct_a1, aad_a1), pt_a1)

        # RFC 5297 Appendix A.2 (multi-component AD + nonce)
        key_a2 = bytes.fromhex(
            '7f7e7d7c7b7a79787776757473727170'
            '404142434445464748494a4b4c4d4e4f'
        )
        aad_a2 = [
            bytes.fromhex(
                '00112233445566778899aabbccddeeff'
                'deaddadadeaddadaffeeddccbbaa9988'
                '7766554433221100'
            ),
            bytes.fromhex('102030405060708090a0'),
            bytes.fromhex('09f911029d74e35bd84156c5635688c0'),
        ]
        pt_a2 = bytes.fromhex(
            '7468697320697320736f6d6520706c61'
            '696e7465787420746f20656e63727970'
            '74207573696e67205349562d414553'
        )
        ct_a2 = bytes.fromhex(
            '7bdb6e3b432667eb06f4d14bff2fbd0f'
            'cb900f2fddbe404326601965c889bf17'
            'dba77ceb094fa663b7a3f748ba8af829'
            'ea64ad544a272e9c485b62a3fd5c0d'
        )
        compat_a2 = _CompatAESSIV(key_a2)
        self.assertEqual(compat_a2.encrypt(pt_a2, aad_a2), ct_a2)
        self.assertEqual(compat_a2.decrypt(ct_a2, aad_a2), pt_a2)

        for key_len in (32, 48, 64):
            key = bytes(range(key_len))
            native = AESSIV(key)
            compat = _CompatAESSIV(key)
            for data in (b'', b'a', b'a' * 15, b'a' * 16, b'a' * 17, bytes(range(200))):
                for aad in (None, [], [b''], [b'TaoSync backup name v1'], [b'one', b'two', b'three']):
                    expected = native.encrypt(data, aad)
                    actual = compat.encrypt(data, aad)
                    self.assertEqual(actual, expected)
                    self.assertEqual(compat.decrypt(expected, aad), data)
                    self.assertEqual(native.decrypt(actual, aad), data)

        with self.assertRaises(InvalidTag):
            compat_a1.decrypt(bytes(flip(ct_a1, 0)), aad_a1)
        with self.assertRaises(InvalidTag):
            compat_a1.decrypt(bytes(flip(ct_a1, len(ct_a1) - 1)), aad_a1)
        with self.assertRaises(InvalidTag):
            compat_a1.decrypt(ct_a1, [b'wrong'])
        with self.assertRaises(InvalidTag):
            compat_a1.decrypt(ct_a1[:15], aad_a1)
        with self.assertRaises(ValueError):
            _CompatAESSIV(b'short')

    def test_legacy_cryptography_28_compatibility(self):
        # Android p4a v2024.01.21 ships cryptography 2.8: no AESSIV, required backend
        # on Scrypt/HKDF, and strict isinstance(..., bytes) checks in AESGCM.
        def strict_scrypt(*args, **kwargs):
            if kwargs.get('backend') is None:
                raise TypeError('Scrypt requires backend in cryptography 2.8')
            return Scrypt(*args, **kwargs)

        def strict_hkdf(*args, **kwargs):
            if kwargs.get('backend') is None:
                raise TypeError('HKDF requires backend in cryptography 2.8')
            return HKDF(*args, **kwargs)

        class StrictBytesAESGCM:
            def __init__(self, key):
                self._inner = AESGCM(key)

            def encrypt(self, nonce, data, associated_data):
                if not isinstance(data, bytes):
                    raise TypeError('data must be bytes')
                if associated_data is not None and not isinstance(associated_data, bytes):
                    raise TypeError('associated_data must be bytes')
                return self._inner.encrypt(nonce, data, associated_data)

            def decrypt(self, nonce, data, associated_data):
                if not isinstance(data, bytes):
                    raise TypeError('data must be bytes')
                if associated_data is not None and not isinstance(associated_data, bytes):
                    raise TypeError('associated_data must be bytes')
                return self._inner.decrypt(nonce, data, associated_data)

        with (
            patch.object(backupCipher, 'AESSIV', None),
            patch.object(backupCipher, 'Scrypt', strict_scrypt),
            patch.object(backupCipher, 'HKDF', strict_hkdf),
            patch.object(backupCipher, 'AESGCM', StrictBytesAESGCM),
        ):
            compat_cipher = BackupCipher('codec tests')
            expected_name = 'tsb-1-j7dfhi4icyrbhlvv7dzcurwhqe2w3h3l3znbhgwnvk6q'
            self.assertEqual(compat_cipher.encode_name('example.txt', False), expected_name)
            self.assertEqual(compat_cipher.decode_name(expected_name, True), 'example.txt')

            long_name = '长文件名-' + 'a' * 160 + '.bin'
            physical, record = compat_cipher.storage_name(long_name)
            self.assertEqual(compat_cipher.decode_record(physical, record), long_name)

            for payload in (b'', b'abc', b'x' * (CHUNK + 99)):
                wire = drain(compat_cipher.encrypt_reader(io.BytesIO(payload), len(payload)))
                compat_cipher.authenticate_prefix(wire[:backupCipher.OWNERSHIP_PREFIX_SIZE])
                target = io.BytesIO()
                writer = compat_cipher.decrypt_writer(target)
                writer.write(wire)
                writer.finish()
                self.assertEqual(target.getvalue(), payload)
                # Ciphertext produced under legacy fallback must also decrypt with native cipher.
                native_target = io.BytesIO()
                native_writer = self.cipher.decrypt_writer(native_target)
                native_writer.write(wire)
                native_writer.finish()
                self.assertEqual(native_target.getvalue(), payload)

    def test_android_startup_import_chain_without_aessiv(self):
        repo_root = str(Path(__file__).resolve().parents[1])
        script = (
            'import cryptography.hazmat.primitives.ciphers.aead as aead\n'
            'if hasattr(aead, "AESSIV"):\n'
            '    delattr(aead, "AESSIV")\n'
            'import controller.jobController\n'
            'import controller.notifyController\n'
            'import controller.systemController\n'
            'import controller.updateController\n'
            'from service.storage import backupCipher\n'
            'assert backupCipher.AESSIV is None\n'
            'c = backupCipher.BackupCipher("codec tests")\n'
            'assert c.encode_name("example.txt", False) == '
            '"tsb-1-j7dfhi4icyrbhlvv7dzcurwhqe2w3h3l3znbhgwnvk6q"\n'
        )
        env = os.environ.copy()
        env['PYTHONPATH'] = repo_root + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
