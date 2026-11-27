import io
import hashlib
import base64
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
from concurrent.futures import ThreadPoolExecutor

import requests

from service.storage.drivers.aliyun import (
    AliyunAPIError, AliyunDriveDriver, _PartReader, _TransferAdapter, _UploadHTTPSConnection,
    _UploadHTTPSConnectionPool,
)
from service.storage.drivers.base import RAPID_UPLOAD, StorageDriver, TransferCancelled, stream_transfer
from service.storage import storageService
from service.engine import engineService


def make_driver(**settings):
    driver = AliyunDriveDriver({
        'client_id': 'test-client', 'client_secret': 'test-secret',
        'refresh_token': 'test-refresh', 'drive_id': 'drive', **settings,
    })
    driver._resolve = Mock(return_value={'file_id': 'parent'})
    driver._assert_file_destination = Mock()
    driver._remove_duplicates = Mock()
    driver._abort_upload = Mock()
    return driver


class PartReaderTests(unittest.TestCase):
    def test_partial_retries_replay_without_consuming_source_twice(self):
        source = io.BytesIO(b'abcdefnext')
        progress = []
        reader = _PartReader(source, 6, None, progress.append)
        try:
            self.assertEqual(reader.read(2), b'ab')
            self.assertEqual(source.tell(), 6)
            reader.reset()
            self.assertEqual(reader.read(4), b'abcd')
            self.assertEqual(reader.read(4), b'ef')
            reader.reset()
            self.assertEqual(reader.read(), b'abcdef')
            self.assertEqual(reader.read(), b'')
            self.assertEqual(sum(progress), 6)
            self.assertEqual(source.read(), b'next')
            self.assertFalse(reader.buffer._rolled)
        finally:
            reader.close()

    def test_cancellation_and_truncated_source_are_not_silently_accepted(self):
        cancel = threading.Event()
        reader = _PartReader(io.BytesIO(b'a'), 2, cancel, lambda _: None)
        try:
            self.assertEqual(reader.read(2), b'a')
            with self.assertRaisesRegex(IOError, 'source stream ended'):
                reader.read(2)
            cancel.set()
            with self.assertRaises(TransferCancelled):
                reader.read(2)
        finally:
            reader.close()


class DirectoryBatchTests(unittest.TestCase):
    def test_concurrent_checks_share_next_fresh_paginated_listing(self):
        driver = make_driver()
        started = threading.Event()
        release = threading.Event()
        queued = threading.Event()
        waiting = set()
        original_wait = driver.list_condition.wait
        requests_seen = []

        def wait(timeout=None):
            waiting.add(threading.get_ident())
            if len(waiting) == 20:
                queued.set()
            return original_wait(timeout)

        def request(endpoint, data):
            requests_seen.append(data.copy())
            if len(requests_seen) == 1:
                started.set()
                if not release.wait(5):
                    raise TimeoutError('test listing was not released')
                return {'items': [{'file_id': 'old'}]}
            if not data['marker']:
                return {'items': [{'file_id': 'committed'}], 'next_marker': 'page2'}
            return {'items': [{'file_id': 'second-page'}]}

        driver._request = Mock(side_effect=request)
        with patch.object(driver.list_condition, 'wait', side_effect=wait), \
                ThreadPoolExecutor(max_workers=21) as pool:
            first = pool.submit(driver._list_id, 'parent')
            try:
                self.assertTrue(started.wait(5))
                followers = [pool.submit(driver._list_id, 'parent') for _ in range(20)]
                self.assertTrue(queued.wait(5))
            finally:
                release.set()
            self.assertEqual(first.result(5), [{'file_id': 'old'}])
            results = [future.result(5) for future in followers]
        self.assertEqual(len(requests_seen), 3)
        for result in results:
            self.assertEqual(result, [{'file_id': 'committed'}, {'file_id': 'second-page'}])
        results[0][0]['file_id'] = 'changed-by-caller'
        self.assertEqual(results[1][0]['file_id'], 'committed')
        self.assertEqual(driver.list_batches, {})
        driver._list_id('parent')
        self.assertEqual(len(requests_seen), 5)

    def test_failed_listing_releases_batch_and_later_calls_retry(self):
        driver = make_driver()
        driver._request = Mock(side_effect=[RuntimeError('offline'), {'items': []}])
        with self.assertRaisesRegex(RuntimeError, 'offline'):
            driver._list_id('parent')
        self.assertEqual(driver.list_batches, {})
        self.assertEqual(driver._list_id('parent'), [])

    def test_failed_shared_batch_wakes_all_waiters(self):
        driver = make_driver()
        started, release, queued = (threading.Event() for _ in range(3))
        waiting = set()
        original_wait = driver.list_condition.wait

        def wait(timeout=None):
            waiting.add(threading.get_ident())
            if len(waiting) == 3:
                queued.set()
            return original_wait(timeout)

        def fetch(parent_id):
            if not started.is_set():
                started.set()
                if not release.wait(5):
                    raise TimeoutError('test listing was not released')
                return []
            raise RuntimeError('listing failed')

        driver._fetch_list_id = Mock(side_effect=fetch)
        with patch.object(driver.list_condition, 'wait', side_effect=wait), \
                ThreadPoolExecutor(max_workers=4) as pool:
            first = pool.submit(driver._list_id, 'parent')
            try:
                self.assertTrue(started.wait(5))
                followers = [pool.submit(driver._list_id, 'parent') for _ in range(3)]
                self.assertTrue(queued.wait(5))
            finally:
                release.set()
            self.assertEqual(first.result(5), [])
            for future in followers:
                with self.assertRaisesRegex(RuntimeError, 'listing failed'):
                    future.result(5)
        self.assertEqual(driver._fetch_list_id.call_count, 2)
        self.assertEqual(driver.list_batches, {})

    def test_different_directories_do_not_block_each_other(self):
        driver = make_driver()
        barrier = threading.Barrier(2)

        def request(endpoint, data):
            barrier.wait(timeout=5)
            return {'items': [{'file_id': data['parent_file_id']}]}

        driver._request = Mock(side_effect=request)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(driver._list_id, 'a')
            second = pool.submit(driver._list_id, 'b')
            self.assertEqual(first.result(5), [{'file_id': 'a'}])
            self.assertEqual(second.result(5), [{'file_id': 'b'}])


class TargetedUploadLookupTests(unittest.TestCase):
    def setUp(self):
        self.driver = make_driver()
        self.addCleanup(self.driver.session.close)

    def test_small_upload_does_not_enumerate_unrelated_siblings(self):
        driver = self.driver
        for method in ('_resolve', '_assert_file_destination', '_remove_duplicates'):
            setattr(driver, method, getattr(AliyunDriveDriver, method).__get__(driver))
        driver._list_id = Mock(side_effect=AssertionError('full directory enumeration'))
        payload = b'a' * (130 * 1024)
        committed = False

        def request(endpoint, data):
            nonlocal committed
            if endpoint.endswith('/search'):
                if "name = 'folder'" in data['query']:
                    return {'items': [{'name': 'folder', 'type': 'folder', 'file_id': 'parent'}]}
                self.assertEqual(data['query'], "parent_file_id = 'parent' and name = 'small.bin'")
                return {'items': [{'name': 'small.bin', 'type': 'file', 'file_id': 'new'}] if committed else []}
            if endpoint.endswith('/create'):
                self.assertNotIn('pre_hash', data)
                return {'file_id': 'new', 'upload_id': 'upload',
                        'part_info_list': [{'part_number': 1, 'upload_url': 'https://example.test/part'}]}
            self.assertTrue(endpoint.endswith('/complete'))
            committed = True
            return {'file_id': 'new'}

        def put(url, data, **kwargs):
            self.assertEqual(data.read(), payload)
            return Mock(status_code=200)

        driver._request = Mock(side_effect=request)
        driver.session.put = Mock(side_effect=put)
        driver.upload('/folder/small.bin', io.BytesIO(payload), len(payload))
        self.assertEqual(driver._request.call_count, 5)
        driver._list_id.assert_not_called()

    def test_search_paginates_duplicate_matches_and_filters_other_names(self):
        self.driver._request = Mock(side_effect=[
            {'items': [{'name': 'same', 'file_id': 'old'}, {'name': 'other'}], 'next_marker': 'next'},
            {'items': [{'name': 'same', 'file_id': 'new'}]},
        ])
        self.assertEqual([item['file_id'] for item in self.driver._find_named('parent', 'same')], ['old', 'new'])
        self.assertEqual(self.driver._request.call_args.args[1]['marker'], 'next')

    def test_unusual_names_use_listing_without_query_interpolation(self):
        name = "someone's file"
        self.driver._list_id = Mock(return_value=[{'name': name}, {'name': 'other'}])
        self.driver._request = Mock()
        self.assertEqual(self.driver._find_named('parent', name), [{'name': name}])
        self.driver._request.assert_not_called()

    def test_cleanup_falls_back_when_search_has_not_seen_commit(self):
        driver = self.driver
        driver._find_named = Mock(return_value=[{'name': 'same', 'file_id': 'old', 'type': 'file'}])
        driver._list_id = Mock(return_value=[
            {'name': 'same', 'file_id': 'new', 'type': 'file'},
            {'name': 'same', 'file_id': 'old', 'type': 'file'},
        ])
        driver._delete_id = Mock()
        AliyunDriveDriver._remove_duplicates(driver, 'parent', 'same', 'new')
        driver._list_id.assert_called_once_with('parent')
        driver._delete_id.assert_called_once_with('old')

    def test_targeted_resolution_falls_back_for_a_new_folder(self):
        driver = self.driver
        driver._find_named = Mock(return_value=[])
        folder = {'name': 'folder', 'file_id': 'parent', 'type': 'folder'}
        driver._list_id = Mock(return_value=[folder])
        self.assertEqual(AliyunDriveDriver._resolve(driver, '/folder', targeted=True), folder)

    def test_preflight_rejects_same_named_folder(self):
        self.driver._find_named = Mock(return_value=[{'name': 'same', 'type': 'folder'}])
        with self.assertRaises(IsADirectoryError):
            AliyunDriveDriver._assert_file_destination(self.driver, 'parent', 'same', '/same')

    def test_search_failure_does_not_delete_existing_files(self):
        self.driver._request = Mock(side_effect=AliyunAPIError('unavailable', 'Forbidden'))
        self.driver._delete_id = Mock()
        with self.assertRaises(AliyunAPIError):
            AliyunDriveDriver._remove_duplicates(self.driver, 'parent', 'same', 'new')
        self.driver._delete_id.assert_not_called()


class UploadConnectionTests(unittest.TestCase):
    def test_upload_prefers_ipv4_and_preserves_tls_hostname(self):
        connection = _UploadHTTPSConnection('cn-beijing-data.aliyundrive.net', timeout=3)
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.1', 443))]
        with patch('service.storage.drivers.aliyun.socket.getaddrinfo', return_value=addresses) as resolve, \
                patch('service.storage.drivers.aliyun.urllib3_connection.create_connection') as connect, \
                patch('urllib3.connection.HTTPSConnection._new_conn') as fallback:
            self.assertIs(connection._new_conn(), connect.return_value)
        resolve.assert_called_once_with(connection.host, 443, socket.AF_INET, socket.SOCK_STREAM)
        connect.assert_called_once_with(('192.0.2.1', 443), 3, source_address=None,
                                        socket_options=connection.socket_options)
        self.assertEqual(connection.host, 'cn-beijing-data.aliyundrive.net')
        self.assertEqual(connection._dns_host, connection.host)
        fallback.assert_not_called()

    def test_ipv4_dns_failure_falls_back_to_normal_dual_stack_connector(self):
        connection = _UploadHTTPSConnection('bucket.oss-cn-beijing.aliyuncs.com')
        with patch('service.storage.drivers.aliyun.socket.getaddrinfo', side_effect=socket.gaierror), \
                patch('urllib3.connection.HTTPSConnection._new_conn') as fallback:
            self.assertIs(connection._new_conn(), fallback.return_value)
        fallback.assert_called_once_with()

    def test_ipv4_connection_failure_tries_other_addresses_then_falls_back(self):
        connection = _UploadHTTPSConnection('cn-beijing-data.aliyundrive.net')
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.1', 443)),
                     (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('192.0.2.2', 443))]
        with patch('service.storage.drivers.aliyun.socket.getaddrinfo', return_value=addresses), \
                patch('service.storage.drivers.aliyun.urllib3_connection.create_connection', side_effect=OSError) as connect, \
                patch('urllib3.connection.HTTPSConnection._new_conn') as fallback:
            self.assertIs(connection._new_conn(), fallback.return_value)
        self.assertEqual(connect.call_count, 2)
        fallback.assert_called_once_with()

    def test_api_hosts_and_proxy_connections_keep_normal_resolution(self):
        for host in ('openapi.alipan.com', 'auth.example.com', '127.0.0.1', 'proxy.example.com'):
            with self.subTest(host=host):
                connection = _UploadHTTPSConnection(host)
                with patch('service.storage.drivers.aliyun.socket.getaddrinfo') as resolve, \
                        patch('urllib3.connection.HTTPSConnection._new_conn') as fallback:
                    self.assertIs(connection._new_conn(), fallback.return_value)
                resolve.assert_not_called()
                fallback.assert_called_once_with()

    def test_adapter_uses_own_pools_and_keeps_certificate_verification(self):
        import urllib3.poolmanager
        original_https_pool = urllib3.poolmanager.pool_classes_by_scheme['https']
        adapter = _TransferAdapter()
        try:
            pool = adapter.poolmanager.connection_from_url('https://cn-beijing-data.aliyundrive.net')
            self.assertIsInstance(pool, _UploadHTTPSConnectionPool)
            self.assertEqual(pool.conn_kw['blocksize'], 256 * 1024)
            adapter.cert_verify(pool, 'https://cn-beijing-data.aliyundrive.net', True, None)
            self.assertEqual(pool.cert_reqs, 'CERT_REQUIRED')
            proxy = adapter.proxy_manager_for('http://127.0.0.1:3128')
            proxy_pool = proxy.connection_from_url('https://cn-beijing-data.aliyundrive.net')
            self.assertNotIsInstance(proxy_pool, _UploadHTTPSConnectionPool)
            self.assertEqual(proxy_pool.proxy.host, '127.0.0.1')
            self.assertIs(urllib3.poolmanager.pool_classes_by_scheme['https'], original_https_pool)
        finally:
            adapter.close()


class UploadTests(unittest.TestCase):
    def test_full_progress_requires_commit_and_duplicate_cleanup(self):
        driver = make_driver()
        progress = []

        def request(endpoint, data):
            if endpoint.endswith('/create'):
                return {'file_id': 'new', 'upload_id': 'upload',
                        'part_info_list': [{'part_number': 1, 'upload_url': 'https://example.test/part'}]}
            self.assertLess(max(progress), 1)
            return {'file_id': 'new'}

        def put(url, data, **kwargs):
            self.assertEqual(data.read(), b'abc')
            self.assertLess(max(progress), 1)
            return Mock(status_code=200)

        driver._request = Mock(side_effect=request)
        driver.session.put = Mock(side_effect=put)
        driver._remove_duplicates.side_effect = lambda *args: self.assertLess(max(progress), 1)
        driver.upload('/file', io.BytesIO(b'abc'), 3, progress.append)
        self.assertEqual(progress, [0.99, 1.0])
        progress.clear()
        driver._remove_duplicates.side_effect = RuntimeError('cleanup failed')
        with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
            driver.upload('/file', io.BytesIO(b'abc'), 3, progress.append)
        self.assertNotIn(1.0, progress)

    def test_connection_drop_mid_part_replays_cached_bytes_and_reads_the_rest(self):
        payload = bytes(range(256)) * (48 * 1024)
        source = io.BytesIO(payload)
        received = []
        attempts = []

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self):
                attempts.append(1)
                if len(attempts) == 1:
                    self.rfile.read(64 * 1024)
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    self.close_connection = True
                    return
                remaining = int(self.headers['Content-Length'])
                digest = hashlib.sha256()
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise IOError('truncated retried upload')
                    remaining -= len(chunk)
                    digest.update(chunk)
                received.append(digest.digest())
                self.send_response(200)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        driver = make_driver()
        driver._request = Mock(side_effect=[{
            'file_id': 'file', 'upload_id': 'upload',
            'part_info_list': [{'part_number': 1, 'upload_url': 'http://127.0.0.1:{}/part'.format(server.server_port)}],
        }, {'file_id': 'file'}])
        progress = []
        try:
            with patch('service.storage.drivers.aliyun.time.sleep'):
                driver.upload('/file', source, len(payload), progress.append)
        finally:
            driver.session.close()
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(received, [hashlib.sha256(payload).digest()])
        self.assertEqual(source.tell(), len(payload))
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 1)

    def test_real_http_retries_and_part_boundaries_preserve_the_payload(self):
        received = []
        payload = b'0123456789'
        source = io.BytesIO(payload)
        self_test = self

        class Handler(BaseHTTPRequestHandler):
            def do_PUT(self):
                self_test.assertEqual(self.headers.get('Content-Length'), '4' if self.path != '/3' else '2')
                self_test.assertIsNone(self.headers.get('Transfer-Encoding'))
                body = self.rfile.read(int(self.headers['Content-Length']))
                received.append((self.path, body))
                self.send_response(503 if len(received) == 1 else 200)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        driver = make_driver()
        driver.PART_SIZE = 4
        urls = [{'part_number': i, 'upload_url': 'http://127.0.0.1:{}/{}'.format(server.server_port, i)}
                for i in range(1, 4)]
        driver._request = Mock(side_effect=[{'file_id': 'file', 'upload_id': 'upload', 'part_info_list': urls},
                                           {'file_id': 'file'}])
        progress = []
        try:
            with patch('service.storage.drivers.aliyun.time.sleep'):
                driver.upload('/file', source, len(payload), progress.append)
        finally:
            driver.session.close()
            server.shutdown()
            server.server_close()
            thread.join()
        self.assertEqual(received, [('/1', b'0123'), ('/1', b'0123'), ('/2', b'4567'), ('/3', b'89')])
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 1)
        driver._abort_upload.assert_not_called()

    def test_put_starts_before_the_entire_source_is_read_and_closes_responses(self):
        driver = make_driver()
        source = io.BytesIO(b'payload')
        response = Mock(status_code=200)
        driver._request = Mock(side_effect=[{
            'file_id': 'file', 'upload_id': 'upload',
            'part_info_list': [{'part_number': 1, 'upload_url': 'https://example.test/part'}],
        }, {'file_id': 'file'}])

        def put(_url, data, **_kwargs):
            self.assertEqual(source.tell(), 0)
            self.assertEqual(data.read(), b'payload')
            return response

        driver.session.put = Mock(side_effect=put)
        try:
            driver.upload('/file', source, 7)
        finally:
            driver.session.close()
        response.close.assert_called_once()

    def test_failure_records_part_and_oss_code_without_signed_url(self):
        driver = make_driver()
        driver._request = Mock(return_value={
            'file_id': 'file', 'upload_id': 'upload',
            'part_info_list': [{'part_number': 1, 'upload_url': 'https://example.test/?secret=hidden'}],
        })
        response = Mock(status_code=503, headers={}, text='<Error><Code>ServiceUnavailable</Code></Error>')
        driver.session.put = Mock(return_value=response)
        try:
            with patch('service.storage.drivers.aliyun.time.sleep'):
                with self.assertRaisesRegex(RuntimeError, r'part 1/1, HTTP 503 ServiceUnavailable') as caught:
                    driver.upload('/file', io.BytesIO(b'payload'), 7)
            self.assertNotIn('hidden', str(caught.exception))
            self.assertEqual(response.close.call_count, 3)
            driver._abort_upload.assert_called_once_with('file')
        finally:
            driver.session.close()

    def test_network_failure_exposes_exception_type(self):
        driver = make_driver()
        driver._request = Mock(return_value={
            'file_id': 'file', 'upload_id': 'upload',
            'part_info_list': [{'part_number': 1, 'upload_url': 'https://example.test/part'}],
        })
        driver.session.put = Mock(side_effect=requests.ReadTimeout('signed URL secret'))
        try:
            with patch('service.storage.drivers.aliyun.time.sleep'):
                with self.assertRaisesRegex(RuntimeError, 'part 1/1, ReadTimeout'):
                    driver.upload('/file', io.BytesIO(b'payload'), 7)
        finally:
            driver.session.close()


class RapidUploadTests(unittest.TestCase):
    def test_rapid_success_does_not_complete_or_rollback_on_cleanup_failure(self):
        self.driver._remove_duplicates.side_effect = RuntimeError('cleanup unavailable')
        source = self.hashed_source()
        with self.assertRaisesRegex(RuntimeError, 'cleanup unavailable'):
            stream_transfer(source, '/source', self.driver, '/file', len(self.payload))
        self.assertFalse(any(url.endswith('/complete') for url, *_ in self.requests))
        self.driver._abort_upload.assert_not_called()
        self.driver.session.put.assert_not_called()

    def test_rapid_success_survives_cancellation_after_create(self):
        cancel = threading.Event()
        request = self.request

        def finish(*args, **kwargs):
            response = request(*args, **kwargs)
            if response.json().get('rapid_upload'):
                cancel.set()
            return response

        self.driver.session.request.side_effect = finish
        source = self.hashed_source()
        stream_transfer(source, '/source', self.driver, '/file', len(self.payload), cancel=cancel)
        self.driver._abort_upload.assert_not_called()
        self.driver._remove_duplicates.assert_called_once()
        self.assertFalse(any(url.endswith('/complete') for url, *_ in self.requests))

    def setUp(self):
        self.driver = make_driver(rapid_upload_min_mb=0)
        self.addCleanup(self.driver.session.close)
        self.payload = bytes(range(256)) * 513
        self.driver.access_token = 'first-access-token'
        self.driver._wait_rate = Mock()
        self.driver._refresh_access_token = Mock()
        self.requests = []
        self.uploaded = []
        # Exercise the real API error and token retry paths.
        self.driver._request = AliyunDriveDriver._request.__get__(self.driver)
        self.driver.session.request = Mock(side_effect=self.request)
        self.driver.session.put = Mock(side_effect=self.put)
        self.prehash_match = True
        self.rapid_match = True
        self.expire_proof_token = False

    def request(self, method, url, json, headers, **kwargs):
        self.requests.append((url, json, headers['Authorization']))
        result = {'file_id': 'new-file', 'upload_id': 'upload'}
        status = 200
        if url.endswith('/create'):
            if 'pre_hash' in json and self.prehash_match:
                status, result = 409, {'code': 'PreHashMatched'}
            elif 'proof_code' in json and self.expire_proof_token:
                self.expire_proof_token = False
                status, result = 401, {'code': 'AccessTokenExpired'}
            elif 'proof_code' in json and self.rapid_match:
                result['rapid_upload'] = True
                result.pop('upload_id')
            else:
                result['part_info_list'] = [{'part_number': 1, 'upload_url': 'https://example.test/part'}]
        return Mock(status_code=status, headers={}, json=lambda: result, text='')

    def put(self, url, data, **kwargs):
        content = bytearray()
        while chunk := data.read(8192):
            content.extend(chunk)
        self.uploaded.append(bytes(content))
        return Mock(status_code=200)

    def test_prehash_match_uses_sha1_and_possession_proof_without_put(self):
        source = io.BytesIO(self.payload)
        progress = []
        self.assertEqual(self.driver.upload('/file', source, len(self.payload), progress.append), RAPID_UPLOAD)
        creates = [item for item in self.requests if item[0].endswith('/create')]
        self.assertEqual(len(creates), 2)
        self.assertEqual(creates[0][1]['pre_hash'], hashlib.sha1(self.payload[:1024]).hexdigest().upper())
        proof = creates[1][1]
        self.assertNotIn('pre_hash', proof)
        self.assertEqual(proof['content_hash'], hashlib.sha1(self.payload).hexdigest().upper())
        self.assertEqual(proof['content_hash_name'], 'sha1')
        self.assertEqual(proof['proof_version'], 'v1')
        offset = int(hashlib.md5(b'first-access-token').hexdigest()[:16], 16) % len(self.payload)
        self.assertEqual(proof['proof_code'], base64.b64encode(self.payload[offset:offset + 8]).decode())
        self.driver.session.put.assert_not_called()
        self.assertFalse(any(url.endswith('/complete') for url, *_ in self.requests))
        self.assertEqual(source.tell(), len(self.payload))
        self.assertEqual(progress, [1.0])
        self.assertIsNone(self.driver.upload_context.cached_source)
        self.driver._remove_duplicates.assert_called_once_with('parent', 'file', 'new-file')

    def hashed_source(self, sha1=None):
        payload = self.payload

        class Source(StorageDriver):
            supports_random_read = True

            def read_range(source, path, offset, length, cancel=None):
                source.ranges.append((offset, length))
                return payload[offset:offset + length]

            def download(source, path, target, progress=None, cancel=None):
                source.downloads += 1
                target.write(payload)

            def list(source, path, details=False):
                return [{'name': 'source', 'is_dir': False, 'size': len(payload),
                         'sha1': sha1 or hashlib.sha1(payload).hexdigest(),
                         'created_at': '2020-01-02T03:04:05+08:00', 'modified_at': 1609459200}]

        source = Source()
        source.downloads, source.ranges = 0, []
        return source

    def test_existing_sha1_reads_only_proof_bytes_and_never_downloads_source(self):
        source = self.hashed_source()
        metadata = source.file_metadata('/source')
        with patch('service.storage.drivers.aliyun.hashlib.sha1') as hash_file, patch(
            'service.storage.drivers.aliyun.tempfile.TemporaryFile'
        ) as cache:
            stream_transfer(source, '/source', self.driver, '/file', len(self.payload), metadata=metadata)
        hash_file.assert_not_called()
        cache.assert_not_called()
        self.assertEqual(source.downloads, 0)
        self.assertEqual(len(source.ranges), 1)
        self.assertLessEqual(source.ranges[0][1], 8)
        create = self.requests[0][1]
        self.assertEqual(create['content_hash'], hashlib.sha1(self.payload).hexdigest().upper())
        self.assertEqual(create['local_created_at'], '2020-01-01T19:04:05.000Z')
        self.assertEqual(create['local_modified_at'], '2021-01-01T00:00:00.000Z')
        self.driver.session.put.assert_not_called()

    def test_existing_sha1_miss_starts_one_stream_and_uploads_original_bytes(self):
        self.rapid_match = False
        source = self.hashed_source()
        self.assertIsNone(stream_transfer(source, '/source', self.driver, '/file', len(self.payload)))
        self.assertEqual(source.downloads, 1)
        self.assertEqual(self.uploaded, [self.payload])
        self.assertEqual(len([item for item in self.requests if item[0].endswith('/create')]), 1)

    def test_original_times_are_also_sent_when_rapid_upload_is_disabled(self):
        self.driver.rapid_upload = False
        source = self.hashed_source()
        stream_transfer(source, '/source', self.driver, '/file', len(self.payload))
        create = self.requests[0][1]
        self.assertNotIn('content_hash', create)
        self.assertEqual(create['local_created_at'], '2020-01-01T19:04:05.000Z')
        self.assertEqual(create['local_modified_at'], '2021-01-01T00:00:00.000Z')
        self.assertEqual(source.ranges, [])
        self.assertEqual(self.uploaded, [self.payload])

    def test_small_streams_skip_rapid_upload_even_with_existing_hash(self):
        self.driver.rapid_upload_min_bytes = 10 * 1024 ** 2
        for hashed in (False, True):
            with self.subTest(hashed=hashed):
                self.requests.clear()
                self.uploaded.clear()
                source = self.hashed_source()
                metadata = source.file_metadata('/source')
                if not hashed:
                    metadata.pop('sha1')
                with patch('service.storage.drivers.aliyun.hashlib.sha1') as digest, \
                        patch('service.storage.drivers.aliyun.tempfile.TemporaryFile') as cache:
                    stream_transfer(source, '/source', self.driver, '/file', len(self.payload), metadata=metadata)
                digest.assert_not_called()
                cache.assert_not_called()
                self.assertEqual(source.ranges, [])
                self.assertEqual(source.downloads, 1)
                self.assertEqual(self.uploaded, [self.payload])
                self.assertTrue(any(url.endswith('/complete') for url, *_ in self.requests))
                creates = [data for url, data, _ in self.requests if url.endswith('/create')]
                self.assertEqual(len(creates), 1)
                self.assertFalse({'pre_hash', 'content_hash', 'proof_code'} & creates[0].keys())

    def test_configured_boundary_for_both_rapid_paths(self):
        for settings, threshold in (
            ({}, 10 * 1024 ** 2), ({'rapid_upload_min_mb': 50}, 50 * 1024 ** 2),
            ({'rapid_upload_threshold': {'value': 3, 'unit': 'KB'}}, 3 * 1024),
            ({'rapid_upload_threshold': {'value': 7, 'unit': 'MB'}}, 7 * 1024 ** 2),
            ({'rapid_upload_threshold': {'value': 1, 'unit': 'GB'}}, 1024 ** 3),
        ):
            driver = make_driver(**settings)
            self.addCleanup(driver.session.close)
            with self.subTest(settings=settings):
                self.check_size_boundary(driver, threshold)

    def check_size_boundary(self, driver, threshold):
        for size in (0, threshold - 1, threshold, threshold + 1):
            for hashed in (False, True):
                with self.subTest(size=size, hashed=hashed):
                    source = Mock()
                    source.metadata = {'sha1': 'A' * 40} if hashed else {}
                    source.can_read_range = True
                    source.read.return_value = b'a' * 1024
                    driver._request = Mock(return_value={'file_id': 'new'})
                    result = driver._create_upload({'size': size}, source, size, None)
                    body = driver._request.call_args.args[1]
                    if size <= threshold:
                        self.assertEqual(body, {'size': size})
                        self.assertIs(result[1], source)
                        source.read.assert_not_called()
                        source.read_range.assert_not_called()
                    elif hashed:
                        self.assertTrue(callable(body))
                    else:
                        self.assertIn('pre_hash', body)

    def test_zero_threshold_tiny_file_prehash_miss_preserves_all_bytes(self):
        self.prehash_match = False
        self.driver.upload('/tiny', io.BytesIO(b'x'), 1)
        self.assertEqual(self.requests[0][1]['pre_hash'], hashlib.sha1(b'x').hexdigest().upper())
        self.assertEqual(self.uploaded, [b'x'])
        self.requests.clear()
        self.driver.upload('/empty', io.BytesIO(b''), 0)
        self.assertFalse({'pre_hash', 'content_hash', 'proof_code'} & self.requests[0][1].keys())

    def test_invalid_rapid_upload_threshold(self):
        for value in (-1, 1.5, '1', None, True, 2**31):
            with self.subTest(value=value), self.assertRaises(ValueError):
                make_driver(rapid_upload_min_mb=value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                make_driver(rapid_upload_threshold={'value': value, 'unit': 'KB'})
        for invalid in (None, 10, {}, {'unit': 'GB'}, {'value': 1}, {'value': 1, 'unit': 'TB'},
                        {'value': 1, 'unit': []}):
            with self.subTest(threshold=invalid), self.assertRaises(ValueError):
                make_driver(rapid_upload_threshold=invalid)

    def test_existing_sha1_recalculates_range_proof_after_token_refresh(self):
        self.expire_proof_token = True
        self.driver._refresh_access_token.side_effect = lambda force=False, **kwargs: setattr(
            self.driver, 'access_token', 'new-token' if force else self.driver.access_token)
        source = self.hashed_source()
        stream_transfer(source, '/source', self.driver, '/file', len(self.payload))
        self.assertEqual(source.downloads, 0)
        self.assertEqual(len(source.ranges), 2)
        for _, data, authorization in self.requests:
            if 'proof_code' not in data:
                continue
            offset = int(hashlib.md5(authorization.removeprefix('Bearer ').encode()).hexdigest()[:16], 16) % len(self.payload)
            self.assertEqual(data['proof_code'], base64.b64encode(self.payload[offset:offset + 8]).decode())

    def test_invalid_source_sha1_falls_back_to_calculating_the_actual_hash(self):
        source = self.hashed_source('not-a-sha1')
        metadata = source.file_metadata('/source')
        stream_transfer(source, '/source', self.driver, '/file', len(self.payload), metadata=metadata)
        self.assertEqual(source.downloads, 1)
        self.assertEqual(metadata['sha1'], hashlib.sha1(self.payload).hexdigest().upper())
        self.assertEqual(len([item for item in self.requests if item[0].endswith('/create')]), 2)

    def test_seekable_source_sha1_preserves_its_position(self):
        source = io.BytesIO(b'prefix' + self.payload)
        source.seek(6)
        source.metadata = {'sha1': hashlib.sha1(self.payload).hexdigest()}
        self.driver.upload('/file', source, len(self.payload))
        self.assertEqual(source.tell(), 6)
        self.assertEqual(self.requests[0][1]['content_hash'], source.metadata['sha1'].upper())

    def test_prehash_miss_replays_prefix_and_keeps_streaming_without_full_cache(self):
        self.prehash_match = False
        source = io.BytesIO(self.payload)
        original_put = self.put

        def put(*args, **kwargs):
            self.assertEqual(source.tell(), 1024)
            self.assertIsNone(self.driver.upload_context.cached_source)
            return original_put(*args, **kwargs)

        self.driver.session.put.side_effect = put
        self.driver.upload('/file', source, len(self.payload))
        self.assertEqual(self.uploaded, [self.payload])
        self.assertEqual(len([item for item in self.requests if item[0].endswith('/create')]), 1)

    def test_hash_miss_uploads_the_cached_file_and_closes_it(self):
        self.rapid_match = False
        source = io.BytesIO(self.payload)
        original_put = self.put
        caches = []

        def put(*args, **kwargs):
            self.assertEqual(source.tell(), len(self.payload))
            caches.append(self.driver.upload_context.cached_source)
            return original_put(*args, **kwargs)

        self.driver.session.put.side_effect = put
        self.driver.upload('/file', source, len(self.payload))
        self.assertEqual(self.uploaded, [self.payload])
        self.assertTrue(caches[0].closed)

    def test_token_refresh_recomputes_proof_with_the_token_used_for_each_request(self):
        self.expire_proof_token = True

        def refresh(force=False, **kwargs):
            if force:
                self.driver.access_token = 'refreshed-access-token'

        self.driver._refresh_access_token.side_effect = refresh
        self.driver.upload('/file', io.BytesIO(self.payload), len(self.payload))
        proofs = [item for item in self.requests if 'proof_code' in item[1]]
        self.assertEqual(len(proofs), 2)
        for _, data, authorization in proofs:
            token = authorization.removeprefix('Bearer ')
            offset = int(hashlib.md5(token.encode()).hexdigest()[:16], 16) % len(self.payload)
            self.assertEqual(data['proof_code'], base64.b64encode(self.payload[offset:offset + 8]).decode())
        self.assertNotEqual(proofs[0][1]['proof_code'], proofs[1][1]['proof_code'])

    def test_small_empty_and_disabled_uploads_skip_hash_preflight(self):
        self.driver.rapid_upload_min_bytes = 1024
        for payload, enabled in ((b'', True), (b'small', True), (self.payload, False)):
            with self.subTest(size=len(payload), enabled=enabled):
                self.requests.clear()
                self.uploaded.clear()
                self.driver.rapid_upload = enabled
                self.driver.upload('/file', io.BytesIO(payload), len(payload))
                self.assertEqual(self.uploaded, [payload])
                self.assertTrue(all('pre_hash' not in item[1] and 'content_hash' not in item[1]
                                    for item in self.requests))

    def test_truncated_source_after_prehash_match_does_not_commit_or_remove_old_file(self):
        with self.assertRaisesRegex(IOError, 'source stream ended'):
            self.driver.upload('/file', io.BytesIO(self.payload[:-1]), len(self.payload))
        self.driver._remove_duplicates.assert_not_called()
        self.driver._abort_upload.assert_not_called()
        self.assertIsNone(self.driver.upload_context.cached_source)
        self.assertFalse(any(item[0].endswith('/complete') for item in self.requests))

    def test_cancellation_during_hashing_closes_cache_and_does_not_commit(self):
        cancel = threading.Event()

        class Source(io.BytesIO):
            def read(source, size=-1):
                data = super().read(size)
                if source.tell() > 1024:
                    cancel.set()
                return data

        with self.assertRaises(TransferCancelled):
            self.driver.upload('/file', Source(self.payload), len(self.payload), cancel=cancel)
        self.assertIsNone(self.driver.upload_context.cached_source)
        self.driver._remove_duplicates.assert_not_called()
        self.assertFalse(any(item[0].endswith('/complete') for item in self.requests))

    def test_api_errors_other_than_prehash_matched_do_not_trigger_full_hash(self):
        error = AliyunAPIError('permission denied', 'Forbidden')
        self.driver._request = Mock(side_effect=error)
        source = io.BytesIO(self.payload)
        with self.assertRaisesRegex(AliyunAPIError, 'permission denied'):
            self.driver.upload('/file', source, len(self.payload))
        self.assertEqual(source.tell(), 1024)
        self.driver._remove_duplicates.assert_not_called()

    def test_rapid_upload_consumes_a_nonseekable_pipe_and_finishes_its_producer(self):
        payload = self.payload
        producer_finished = threading.Event()

        class Source:
            def download(source, path, target, progress=None, cancel=None):
                for offset in range(0, len(payload), 97):
                    target.write(payload[offset:offset + 97])
                producer_finished.set()

        stream_transfer(Source(), '/source', self.driver, '/file', len(payload))
        self.assertTrue(producer_finished.is_set())
        self.driver.session.put.assert_not_called()


class BrowseTests(unittest.TestCase):
    def test_browse_uses_selected_space_and_filters_files(self):
        driver = Mock()
        driver._list_id.return_value = [
            {'file_id': 'folder', 'type': 'folder', 'name': 'Photos'},
            {'file_id': 'file', 'type': 'file', 'name': 'secret.txt'},
        ]
        for key in ('access_token', 'refresh_token', 'refresh_proof', 'expires_at'):
            setattr(driver, key, key)
        with patch.object(storageService, '_requireTaoSync'), patch.object(
            storageService, 'createDriver', return_value=driver
        ) as create:
            result = storageService.browseAliyun({'engineId': 1, 'parentId': 'parent', 'config': {
                'client_id': 'client', 'client_secret': 'secret', 'refresh_token': 'refresh',
                'drive_type': 'backup', 'drive_id': 'stale', 'root_folder_id': 'old-root',
            }})
        self.assertEqual(result['directories'], [{'id': 'folder', 'name': 'Photos'}])
        config = create.call_args.args[1]
        self.assertEqual(config['drive_type'], 'backup')
        self.assertEqual(config['root_folder_id'], 'root')
        self.assertNotIn('drive_id', config)
        driver._list_id.assert_called_once_with('parent')
        driver.session.close.assert_called_once()

    def test_another_engines_mount_cannot_be_browsed(self):
        with patch.object(storageService, '_requireTaoSync'), patch.object(
            storageService.storageMapper, 'getMountById', return_value={'engineId': 2, 'driverType': 'aliyun'}
        ), patch.object(storageService, 'createDriver') as create:
            with self.assertRaises(ValueError):
                storageService.browseAliyun({'engineId': 1, 'mountId': 9})
            create.assert_not_called()


class ConcurrencyConfigTests(unittest.TestCase):
    def test_invalid_limits_are_rejected(self):
        for value in (True, 0, -1, 101, 1.5, None, '5.0'):
            with self.assertRaises(ValueError):
                engineService.updateCopyConcurrency(1, value)

    def test_setting_limit_updates_database_and_shared_limiter(self):
        limiter = engineService.CopyLimiter(5)
        with patch.object(engineService, 'getEngineById', return_value={'engineType': 'alist'}), \
                patch.object(engineService, 'getCopyLimiter', return_value=limiter), patch(
            'mapper.alistMapper.updateCopyConcurrency'
        ) as persist:
            engineService.updateCopyConcurrency(1, 8)
        persist.assert_called_once_with(1, 8)
        self.assertEqual(limiter.limit, 8)

    def test_builtin_engine_rejects_the_obsolete_global_setting(self):
        with patch.object(engineService, 'getEngineById', return_value={'engineType': 'taosync'}), \
                patch.object(engineService, 'getCopyLimiter') as get_limiter:
            with self.assertRaisesRegex(ValueError, 'each storage directory'):
                engineService.updateCopyConcurrency(1, 8)
        get_limiter.assert_not_called()

    def test_mount_limiter_is_shared_and_defaults_to_five_independently_of_engine(self):
        with patch.dict(engineService.copyLimiters, clear=True), patch.object(
            engineService.storageMapper, 'getMountById',
            side_effect=lambda mount_id: {'id': mount_id, 'copyConcurrency': 2 if mount_id == 11 else 5},
        ) as load:
            first = engineService.getMountCopyLimiter(11)
            self.assertIs(first, engineService.getMountCopyLimiter(11))
            other = engineService.getMountCopyLimiter(12)
            self.assertEqual((first.limit, other.limit), (2, 5))
            self.assertEqual(load.call_count, 2)

    def test_failed_persistence_does_not_change_the_live_directory_limit(self):
        limiter = engineService.CopyLimiter(5)
        with patch.object(engineService, 'getMountCopyLimiter', return_value=limiter):
            with self.assertRaisesRegex(OSError, 'database unavailable'):
                engineService.updateMountCopyConcurrency(11, 8, persist=Mock(side_effect=OSError('database unavailable')))
        self.assertEqual(limiter.limit, 5)
