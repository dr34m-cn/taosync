import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.request import ProxyHandler, build_opener

import fake_alist
from fake_alist import FakeAlist


class FakeAlistLifecycleTest(unittest.TestCase):
    def test_server_serves_requests_and_closes_its_loop(self):
        fake = FakeAlist()
        self.addCleanup(fake.stop)
        url = fake.start()
        with build_opener(ProxyHandler({})).open(url + '/api/me', timeout=5) as response:
            self.assertEqual(json.load(response)['data']['username'], 'admin')
        fake.stop()
        self.assertFalse(fake.thread.is_alive())
        self.assertTrue(fake.loop.is_closed())

    def test_startup_failure_reaches_the_test_thread(self):
        fake = FakeAlist()
        self.addCleanup(fake.stop)
        error = OSError('bind failed')
        with mock.patch.object(fake_alist, 'bind_sockets', side_effect=error):
            with self.assertRaisesRegex(RuntimeError, 'failed to start') as raised:
                fake.start()
        self.assertIs(raised.exception.__cause__, error)
        self.assertFalse(fake.thread.is_alive())
        self.assertTrue(fake.loop.is_closed())

    def test_stop_waits_for_pending_copies_before_directory_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, destination = Path(tmp, 'source'), Path(tmp, 'destination')
            fake = FakeAlist()
            self.addCleanup(fake.stop)
            fake.storage('/source', str(source))
            fake.storage('/destination', str(destination))
            Path(source, 'file.txt').write_text('payload', encoding='utf-8')
            task_id = fake.copy('/source', '/destination', 'file.txt')
            fake.stop()
            self.assertEqual(fake.tasks[task_id]['state'], 2)
            self.assertEqual(Path(destination, 'file.txt').read_text(encoding='utf-8'), 'payload')
            self.assertTrue(all(not worker.is_alive() for worker in fake.workers))
