import io
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from smbprotocol.exceptions import SMBException

from service.storage.drivers.base import stream_transfer
from service.storage.drivers.smb import SmbDriver


class _Connection:
    def __init__(self, credits=3):
        self.sequence_lock = threading.Lock()
        self.sequence_window = {"low": 0, "high": credits}
        self.closed = False
        self.echoes = []

    def echo(self, sid, credit_request):
        self.echoes.append((sid, credit_request))
        self.sequence_window["high"] += credit_request

    def disconnect(self, close=True):
        if close and self.sequence_window["high"] == self.sequence_window["low"]:
            raise SMBException("no credits available for logoff")
        self.closed = True


class _Client:
    def __init__(self, credits=3):
        self.credits = credits
        self.connections = []
        self.caches = []
        self.stat_hook = None
        self.payload = b"data"
        self.written = {}
        self.path = SimpleNamespace(exists=lambda *_args, **_kwargs: False)

    def register_session(self, server, connection_cache, **kwargs):
        if server not in connection_cache:
            connection_cache[server] = _Connection(self.credits)
            self.connections.append(connection_cache[server])
            self.caches.append(connection_cache)
        return SimpleNamespace(connection=connection_cache[server], session_id=1)

    def reset_connection_cache(self, connection_cache, **kwargs):
        for connection in connection_cache.values():
            connection.disconnect()
        connection_cache.clear()

    def stat(self, path, connection_cache, **kwargs):
        connection = next(iter(connection_cache.values()))
        if self.stat_hook:
            self.stat_hook(path, connection)
        if path.endswith("destination"):
            raise FileNotFoundError(path)
        return SimpleNamespace(st_size=len(self.payload), st_mode=0, st_file_attributes=0)

    @contextmanager
    def scandir(self, path, **kwargs):
        yield []

    @contextmanager
    def open_file(self, path, mode, **kwargs):
        with io.BytesIO(self.payload if mode == "rb" else b"") as stream:
            yield stream
            if mode == "wb":
                self.written[path] = stream.getvalue()

    def makedirs(self, path, **kwargs):
        pass

    def replace(self, source, destination, **kwargs):
        self.written[destination] = self.written.pop(source)


class SmbConnectionTests(unittest.TestCase):
    def setUp(self):
        self.client = _Client()
        self.module = patch.dict("sys.modules", {"smbclient": self.client})
        self.module.start()
        self.addCleanup(self.module.stop)
        self.driver = SmbDriver({"host": "server", "share": "share"})
        self.addCleanup(self.driver.close)

    def test_scan_does_not_share_credits_with_an_active_operation(self):
        active = threading.Event()
        release = threading.Event()

        def stat(path, connection):
            with connection.sequence_lock:
                available = connection.sequence_window["high"] - connection.sequence_window["low"]
                if available < 3:
                    raise SMBException("Request requires 1 credits but only 0 credits are available")
                connection.sequence_window["low"] += 3
            try:
                if path.endswith("first"):
                    active.set()
                    if not release.wait(5):
                        raise TimeoutError("operation was not released")
            finally:
                connection.sequence_window["high"] += 3

        self.client.stat_hook = stat
        with ThreadPoolExecutor(max_workers=2) as workers:
            first = workers.submit(self.driver.list, "/first")
            try:
                self.assertTrue(active.wait(5))
                second = workers.submit(self.driver.list, "/second")
                self.assertEqual(second.result(timeout=5), [])
                self.assertEqual(len(self.client.connections), 2)
            finally:
                release.set()
            self.assertEqual(first.result(timeout=5), [])

    def test_successful_operations_reuse_an_idle_connection(self):
        self.driver.list("/")
        self.driver.list("/")
        self.assertEqual(len(self.client.connections), 1)
        self.assertFalse(self.client.connections[0].closed)

    def test_failed_operation_discards_its_connection(self):
        error = SMBException("Request requires 1 credits but only 0 credits are available")

        def fail(path, connection):
            connection.sequence_window["low"] = connection.sequence_window["high"]
            raise error

        self.client.stat_hook = fail
        with self.assertRaises(SMBException) as caught:
            self.driver.list("/nested")
        self.assertIs(caught.exception, error)
        self.assertTrue(self.client.connections[0].closed)

        self.client.stat_hook = None
        self.assertEqual(self.driver.list("/nested"), [])
        self.assertEqual(len(self.client.connections), 2)

    def test_low_credit_connection_requests_room_for_compound_stat(self):
        self.client.credits = 2
        self.driver.list("/nested")
        self.assertEqual(self.client.connections[0].echoes, [(1, 64)])

    def test_idle_connection_with_no_credits_is_replaced(self):
        self.driver.list("/")
        connection = self.client.connections[0]
        connection.sequence_window["low"] = connection.sequence_window["high"]
        self.driver.list("/")
        self.assertTrue(connection.closed)
        self.assertEqual(len(self.client.connections), 2)

    def test_idle_pool_is_bounded_after_concurrent_operations(self):
        count = self.driver._MAX_IDLE_CONNECTIONS + 2
        barrier = threading.Barrier(count)
        self.client.stat_hook = lambda *_args: barrier.wait(timeout=5)
        with ThreadPoolExecutor(max_workers=count) as workers:
            results = list(workers.map(self.driver.list, ["/nested"] * count))
        self.assertEqual(results, [[]] * count)
        self.assertEqual(len(self.client.connections), count)
        self.assertEqual(
            sum(not connection.closed for connection in self.client.connections),
            self.driver._MAX_IDLE_CONNECTIONS,
        )

    def test_mounts_do_not_reuse_each_others_connections(self):
        other = SmbDriver({"host": "server", "share": "other"})
        self.addCleanup(other.close)
        self.driver.list("/")
        other.list("/")
        self.assertEqual(len(self.client.connections), 2)
        self.assertIsNot(self.client.caches[0], self.client.caches[1])

    def test_close_releases_idle_connections(self):
        self.driver.list("/")
        self.driver.close()
        self.assertTrue(self.client.connections[0].closed)

    def test_close_does_not_disconnect_an_operation_in_progress(self):
        active = threading.Event()
        release = threading.Event()

        def stat(path, connection):
            active.set()
            if not release.wait(5):
                raise TimeoutError("operation was not released")
            self.assertFalse(connection.closed)

        self.client.stat_hook = stat
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(self.driver.list, "/nested")
            try:
                self.assertTrue(active.wait(5))
                self.driver.close()
                self.assertFalse(self.client.connections[0].closed)
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=5), [])
        self.assertTrue(self.client.connections[0].closed)

    def test_copy_within_the_same_mount_keeps_both_streams_working(self):
        self.client.payload *= 256 * 1024
        errors = []

        def copy():
            try:
                stream_transfer(
                    self.driver, "/source", self.driver, "/destination",
                    len(self.client.payload),
                )
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=copy, daemon=True)
        worker.start()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive(), "same-mount copy stalled")
        self.assertEqual(errors, [])
        self.assertEqual(
            self.client.written[r"\\server\share\destination"], self.client.payload
        )


if __name__ == "__main__":
    unittest.main()
