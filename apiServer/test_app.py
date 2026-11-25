import asyncio
import json
import tempfile
from pathlib import Path
from contextlib import closing
import sqlite3
import time
import unittest
from unittest import mock

import tornado.testing

try:
    from .app import AliyunOAuthClient, SessionStore, SyncTotals, make_app
except ImportError:  # pragma: no cover - unittest discovery may import this as a script module
    from app import AliyunOAuthClient, SessionStore, make_app


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


class AliyunOAuthClientTest(unittest.TestCase):
    def setUp(self):
        self.session = mock.Mock()
        self.client = AliyunOAuthClient(
            {
                "client_id": "app-id",
                "client_secret": "app-secret",
                "authorize_url": "https://openapi.alipan.com/oauth/authorize",
                "token_url": "https://openapi.alipan.com/oauth/access_token",
                "qr_authorize_url": "https://openapi.alipan.com/oauth/authorize/qrcode",
                "qr_status_url": "https://openapi.alipan.com/oauth/qrcode/{sid}/status",
                "callback_url": "https://auth.example.com/v1/aliyun/callback",
                "scope": "user:base,file:all:read,file:all:write",
                "signing_secret": "test-signing-secret-with-32-characters",
            },
            session=self.session,
        )

    def test_authorization_url_contains_callback_scope_and_state(self):
        url = self.client.authorization_url("state-value")
        self.assertIn("client_id=app-id", url)
        self.assertIn("response_type=code", url)
        self.assertIn("state=state-value", url)
        self.assertIn("redirect_uri=https%3A%2F%2Fauth.example.com%2Fv1%2Faliyun%2Fcallback", url)

    def test_refresh_uses_server_side_secret_and_preserves_old_refresh_token(self):
        self.session.post.return_value = Response({"access_token": "access", "expires_in": 7200})
        proof = self.client._proof("refresh-old")
        result = self.client.refresh("refresh-old", proof)
        self.assertEqual("refresh-old", result["refresh_token"])
        self.assertEqual(proof, result["refresh_proof"])
        payload = self.session.post.call_args.kwargs["json"]
        self.assertEqual("app-secret", payload["client_secret"])
        self.assertEqual("refresh_token", payload["grant_type"])

    def test_refresh_rejects_invalid_proof(self):
        with self.assertRaises(PermissionError):
            self.client.refresh("refresh-old", "0" * 64)

    def test_qr_session_and_status(self):
        self.session.post.return_value = Response({"sid": "sid-value"})
        qr = self.client.create_qr_session()
        self.assertEqual("sid-value", qr["sid"])
        self.assertIn("sid=sid-value", qr["authorization_url"])
        self.session.get.return_value = Response(
            {"status": "LoginSuccess", "authCode": "auth-code"}
        )
        status = self.client.qr_status("sid-value")
        self.assertEqual("LoginSuccess", status["status"])
        self.assertEqual("auth-code", status["auth_code"])


class SessionStoreTest(unittest.TestCase):
    def test_claim_is_one_time(self):
        now = [100.0]
        store = SessionStore(ttl=300, clock=lambda: now[0])
        item = store.create("127.0.0.1")
        store.complete(item.state, {"access_token": "a", "refresh_token": "r"})
        self.assertEqual("r", store.claim(item.session_id, item.poll_token)["refresh_token"])
        with self.assertRaises(KeyError):
            store.claim(item.session_id, item.poll_token)

    def test_expired_session_cannot_be_read(self):
        now = [100.0]
        store = SessionStore(ttl=60, clock=lambda: now[0])
        item = store.create("127.0.0.1")
        now[0] = 161.0
        with self.assertRaises(KeyError):
            store.get(item.session_id, item.poll_token)


class SessionCreateNonBlockingTest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        oauth = mock.Mock()

        def slow_qr_session():
            time.sleep(0.5)
            return {"sid": "sid-value", "authorization_url": "https://example.com/qr?sid=sid-value"}

        oauth.create_qr_session.side_effect = slow_qr_session
        self.store = SessionStore(ttl=300, max_sessions_per_ip=10)
        db = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'trust.db'
        return make_app({"server": {}, 'trust': {'database': db}}, oauth=oauth, store=self.store)

    @tornado.testing.gen_test(timeout=10)
    async def test_other_requests_are_served_while_upstream_qr_request_is_slow(self):
        create = self.http_client.fetch(self.get_url("/v1/aliyun/sessions"), method="POST", body="{}")
        start = time.monotonic()
        health = await self.http_client.fetch(self.get_url("/health"))
        elapsed = time.monotonic() - start
        response = await create
        self.assertEqual(200, health.code)
        self.assertLess(elapsed, 0.4)
        self.assertEqual(201, response.code)
        data = json.loads(response.body)
        self.assertEqual("qrcode", data["mode"])
        self.assertTrue(data["qr_code"].startswith("data:image/png;base64,"))
        item = self.store.sessions[data["session_id"]]
        self.assertEqual("sid-value", item.provider_sid)


class AnonymousStatsTest(tornado.testing.AsyncHTTPTestCase):
    def get_app(self):
        db = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'trust.db'
        return make_app({'server': {}, 'trust': {'database': db}}, oauth=object(), store=object())

    @tornado.testing.gen_test
    async def test_concurrent_reports_are_visible_without_sql_until_checkpoint(self):
        totals = self._app.settings['sync_totals']
        url = self.get_url('/v1/stats')
        size = 2**60 + 1
        with mock.patch.object(sqlite3, 'connect', side_effect=AssertionError('unexpected DB access')):
            responses = await asyncio.gather(*(self.http_client.fetch(url, method='POST',
                headers={'Content-Type': 'application/json'}, body=json.dumps({'files': 3, 'bytes': size}))
                for _ in range(40)))
            self.assertTrue(all(r.code == 204 for r in responses))
            read = await self.http_client.fetch(url)
            self.assertEqual(read.headers['Access-Control-Allow-Origin'], '*')
            self.assertEqual(json.loads(read.body), {'files': '120', 'bytes': str(size * 40)})
        with closing(sqlite3.connect(totals.database)) as db:
            self.assertEqual(db.execute('SELECT files, bytes FROM totals').fetchone(), ('0', '0'))
        await totals.checkpoint()
        self.assertEqual(SyncTotals(totals.database).snapshot(), (120, 40 * size))

    def test_invalid_reports_do_not_change_totals(self):
        for body in ({}, [], {'files': True, 'bytes': 0}, {'files': -1, 'bytes': 0},
                     {'files': 1, 'bytes': '1'}, {'files': 1, 'bytes': 1, 'name': 'extra'},
                     {'files': 1, 'bytes': -1}, {'files': 1, 'bytes': 2**63}):
            with self.subTest(body=body):
                response = self.fetch('/v1/stats', method='POST', headers={'Content-Type': 'application/json'},
                                      body=json.dumps(body))
                self.assertEqual(response.code, 400)
        self.assertEqual(self._app.settings['sync_totals'].snapshot(), (0, 0))


if __name__ == "__main__":
    unittest.main()
