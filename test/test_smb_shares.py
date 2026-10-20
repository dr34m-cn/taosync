import unittest

from service.storage.smbShares import _unpack_share_info, _validate_config


class SmbShareConfigTest(unittest.TestCase):
    def test_host_and_port_are_normalized(self):
        self.assertEqual(
            _validate_config({'host': ' fileserver ', 'port': '1445'}),
            ('fileserver', 1445, '', ''),
        )

    def test_domain_is_prefixed_to_username(self):
        self.assertEqual(
            _validate_config(
                {'host': 'fileserver', 'domain': 'WORKGROUP', 'username': 'alice'}
            )[2],
            'WORKGROUP\\alice',
        )

    def test_invalid_host_and_port_are_rejected(self):
        with self.assertRaises(ValueError):
            _validate_config({'host': r'fileserver\\share'})
        with self.assertRaises(ValueError):
            _validate_config({'host': 'fileserver', 'port': 65536})
        with self.assertRaises(ValueError):
            _validate_config({'host': 'fileserver', 'port': 0})


class SmbShareResponseTest(unittest.TestCase):
    @staticmethod
    def _string_field(value):
        encoded = (value + '\x00').encode('utf-16-le')
        length = len(value) + 1
        return b'\x00' * 8 + length.to_bytes(4, 'little') + encoded

    def test_only_disk_tree_shares_are_returned(self):
        entries = bytearray(48 + 24)
        entries[36:40] = (2).to_bytes(4, 'little')
        # First entry is a disk share; second is IPC$ and must be ignored.
        entries[52:56] = (0).to_bytes(4, 'little')
        entries[64:68] = (3).to_bytes(4, 'little')
        entries.extend(self._string_field('Media'))
        entries.extend(self._string_field('Documents'))
        entries.extend(self._string_field('IPC$'))
        entries.extend(self._string_field('Remote IPC'))

        self.assertEqual(
            _unpack_share_info(entries),
            [{'name': 'Media', 'comment': 'Documents'}],
        )
