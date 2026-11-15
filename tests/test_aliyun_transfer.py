import io
import hashlib
import base64
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import requests

from service.storage.drivers.aliyun import (
    AliyunAPIError, AliyunDriveDriver, _PartReader, _TransferAdapter, _UploadHTTPSConnection,
    _UploadHTTPSConnectionPool,
)
from service.storage.drivers.base import StorageDriver, TransferCancelled, stream_transfer
from service.storage import storageService
from service.engine import engineService


def make_driver():
    driver = AliyunDriveDriver({
        'client_id': 'test-client', 'client_secret': 'test-secret',
        'refresh_token': 'test-refresh', 'drive_id': 'drive',
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
    def setUp(self):
        self.driver = make_driver()
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
        self.driver.upload('/file', source, len(self.payload), progress.append)
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
        stream_transfer(source, '/source', self.driver, '/file', len(self.payload))
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
