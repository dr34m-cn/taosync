import io
import threading
import unittest
from unittest.mock import Mock, patch

from service.storage.backupCipher import (
    BackupCipher, ForeignBackupName, InvalidBackupData, InvalidBackupName,
    decrypted_size, encrypted_size,
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
