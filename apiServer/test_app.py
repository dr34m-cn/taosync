import unittest
from unittest import mock

try:
    from .app import AliyunOAuthClient, SessionStore
except ImportError:  # pragma: no cover - unittest discovery may import this as a script module
    from app import AliyunOAuthClient, SessionStore


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


if __name__ == "__main__":
    unittest.main()
