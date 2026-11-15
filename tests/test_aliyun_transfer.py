import io
import hashlib
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import requests

from service.storage.drivers.aliyun import (
    AliyunDriveDriver, _PartReader, _TransferAdapter, _UploadHTTPSConnection,
    _UploadHTTPSConnectionPool,
)
from service.storage.drivers.base import TransferCancelled
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
        with patch.object(engineService, 'getCopyLimiter', return_value=limiter), patch(
            'mapper.alistMapper.updateCopyConcurrency'
        ) as persist:
            engineService.updateCopyConcurrency(1, 8)
        persist.assert_called_once_with(1, 8)
        self.assertEqual(limiter.limit, 8)
