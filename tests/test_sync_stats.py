import unittest
from unittest.mock import MagicMock, patch

from service.system import syncStats


class SyncStatsTest(unittest.TestCase):
    def test_only_successful_file_transfers_are_scheduled(self):
        items = [dict(isPath=0, type=0, fileSize=20, fileName='private'),
                 dict(isPath=0, type=2, fileSize=8), dict(isPath=0, type=0, fileSize=0),
                 dict(isPath=1, type=0, fileSize=None), dict(isPath=0, type=1, fileSize=70)]
        with patch.object(syncStats, '_enabled', return_value=True), patch.object(syncStats._sender, 'submit') as submit:
            syncStats.report(items)
        submit.assert_called_once_with(syncStats._send, 3, 28)

    def test_empty_runs_do_not_send_zero_totals(self):
        items = [dict(isPath=1, type=0, fileSize=None), dict(isPath=0, type=1, fileSize=70)]
        with patch.object(syncStats, '_enabled', return_value=True), patch.object(syncStats._sender, 'submit') as submit:
            syncStats.report(items)
        submit.assert_not_called()

    def test_opt_out_skips_new_and_queued_reports(self):
        with patch.object(syncStats, '_enabled', return_value=False), patch.object(syncStats._sender, 'submit') as submit, \
                patch.object(syncStats.requests, 'Session') as session:
            syncStats.report([])
            syncStats._send(1, 10)
        submit.assert_not_called()
        session.assert_not_called()

    def test_destination_and_payload_are_fixed_and_no_redirects_followed(self):
        session = MagicMock()
        with patch.object(syncStats, '_enabled', return_value=True), patch.object(syncStats.requests, 'Session') as factory:
            factory.return_value.__enter__.return_value = session
            syncStats._send(2, 7)
        session.post.assert_called_once_with('https://taoapi.dr34m.cn/v1/stats', json={'files': 2, 'bytes': 7},
                                             timeout=(3, 5), allow_redirects=False, stream=True)
        self.assertIs(session.trust_env, False)
