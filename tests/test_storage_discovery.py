import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from service.storage import discoveryService


class LocalBrowseTests(unittest.TestCase):
    def test_default_path_is_cwd_and_symlinks_are_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "alpha").mkdir()
            (root / "zeta").mkdir()
            (root / "file.txt").write_text("x", encoding="utf-8")
            link = root / "link"
            try:
                link.symlink_to(root / "alpha", target_is_directory=True)
            except (OSError, NotImplementedError):
                link = None

            with patch.object(discoveryService.os, "getcwd", return_value=str(root)):
                result = discoveryService.localBrowse()

            self.assertEqual(result["path"], os.path.abspath(str(root)))
            self.assertEqual(result["parent"], os.path.dirname(os.path.abspath(str(root))))
            self.assertEqual([item["name"] for item in result["directories"]], ["alpha", "zeta"])
            if link is not None:
                self.assertNotIn("link", [item["name"] for item in result["directories"]])
            self.assertTrue(all(set(item) == {"name", "path"} for item in result["roots"]))

    def test_path_must_be_absolute_existing_directory(self):
        with self.assertRaisesRegex(ValueError, "absolute"):
            discoveryService.localBrowse("relative/path")
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "existing directory"):
                discoveryService.localBrowse(str(Path(directory) / "missing"))

    def test_permission_errors_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "visible").mkdir()
            with patch.object(
                discoveryService.os,
                "scandir",
                side_effect=PermissionError("denied"),
            ):
                with self.assertRaisesRegex(ValueError, "not accessible"):
                    discoveryService.localBrowse(str(root))

    def test_selected_symlink_is_canonicalized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable")
            result = discoveryService.localBrowse(str(link))
            self.assertEqual(result["path"], os.path.realpath(str(link)))


class SmbDiscoveryTests(unittest.TestCase):
    def test_networks_are_private_and_bounded(self):
        with patch.object(
            discoveryService,
            "MAX_DISCOVERY_NETWORKS",
            2,
        ):
            networks = discoveryService._candidate_networks(
                ["192.168.1.10", "192.168.1.20", "10.0.0.2", "8.8.8.8", "127.0.0.1"]
            )
        self.assertEqual([str(network) for network in networks], ["192.168.1.0/24", "10.0.0.0/24"])

    def test_only_rfc1918_and_link_local_addresses_are_accepted(self):
        self.assertTrue(discoveryService._is_allowed_ipv4("10.0.0.8"))
        self.assertTrue(discoveryService._is_allowed_ipv4("172.20.0.8"))
        self.assertTrue(discoveryService._is_allowed_ipv4("192.168.0.8"))
        self.assertTrue(discoveryService._is_allowed_ipv4("169.254.0.8"))
        for address in ("192.0.2.8", "198.51.100.8", "100.64.0.8", "8.8.8.8", "127.0.0.1"):
            self.assertFalse(discoveryService._is_allowed_ipv4(address), address)

    def test_host_limit_and_no_caller_network_parameter(self):
        network = discoveryService.ipaddress.ip_network("192.168.4.0/24")
        with patch.object(discoveryService, "MAX_DISCOVERY_HOSTS", 3):
            hosts = discoveryService._candidate_hosts([network])
        self.assertEqual(hosts, ["192.168.4.1", "192.168.4.2", "192.168.4.3"])

    def test_scan_deduplicates_active_hosts_and_resolves_name(self):
        discoveryService.clear_smb_discovery_cache()
        with patch.object(
            discoveryService,
            "_candidate_networks",
            return_value=[discoveryService.ipaddress.ip_network("192.168.10.0/30")],
        ), patch.object(
            discoveryService,
            "_candidate_hosts",
            return_value=["192.168.10.1", "192.168.10.2", "192.168.10.1"],
        ), patch.object(
            discoveryService,
            "_probe_smb_port",
            side_effect=lambda address: address if address.endswith(".1") else None,
        ), patch.object(
            discoveryService,
            "_reverse_lookup",
            return_value="nas.local",
        ):
            result = discoveryService.smbDiscover()
        self.assertEqual(result, [{"address": "192.168.10.1", "name": "nas.local"}])

    def test_scan_result_is_cached_and_callers_get_independent_copies(self):
        discoveryService.clear_smb_discovery_cache()
        with patch.object(
            discoveryService, "_smb_discover_uncached", return_value=[{"address": "10.0.0.2", "name": "nas"}]
        ) as scan:
            first = discoveryService.smbDiscover()
            first[0]["name"] = "mutated"
            second = discoveryService.smbDiscover()
        self.assertEqual(second, [{"address": "10.0.0.2", "name": "nas"}])
        scan.assert_called_once_with()
        discoveryService.clear_smb_discovery_cache()

    def test_result_and_reverse_lookup_counts_are_bounded(self):
        addresses = ["10.0.0.{}".format(index) for index in range(1, 8)]
        with patch.object(discoveryService, "MAX_DISCOVERY_RESULTS", 5), patch.object(
            discoveryService, "MAX_REVERSE_LOOKUPS", 2
        ), patch.object(
            discoveryService,
            "_reverse_lookup",
            side_effect=lambda address: "name-" + address,
        ) as lookup:
            result = discoveryService._format_smb_devices(addresses)
        self.assertEqual(len(result), 5)
        self.assertEqual(lookup.call_count, 2)
        self.assertEqual(result[2]["name"], result[2]["address"])

    def test_probe_uses_tcp_445_short_timeout_and_closes_socket(self):
        sock = MagicMock()
        sock.connect_ex.return_value = 0
        with patch.object(discoveryService.socket, "socket", return_value=sock):
            self.assertEqual(discoveryService._probe_smb_port("192.168.1.3", 0.07), "192.168.1.3")
        sock.settimeout.assert_called_once_with(0.07)
        sock.connect_ex.assert_called_once_with(("192.168.1.3", 445))
        sock.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
