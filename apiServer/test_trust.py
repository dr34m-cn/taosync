import json
import tempfile
from pathlib import Path

from tornado.testing import AsyncHTTPTestCase

from apiServer.app import make_app
from apiServer.trust import snapshot
from apiServer.trust_manifest import encode_manifest, parse_manifest


class TrustServiceTest(AsyncHTTPTestCase):
    key = 'service-test-only-' * 3
    first = ('v1-dev', 'linux-amd64', 'a' * 64)
    rebuilt = ('v1-dev', 'linux-amd64', 'b' * 64)
    second = ('v1-pre', 'linux-arm64', 'c' * 64)

    def get_app(self):
        self.db = Path(self.enterContext(tempfile.TemporaryDirectory())) / 'trust.db'
        return make_app({'server': {}, 'trust': {'api_key': self.key, 'database': self.db}},
                        oauth=object(), store=object())

    def push(self, body, key=None):
        return self.fetch('/v1/trust/manifest', method='POST', body=body, headers={
            'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (key or self.key)})

    def test_key_required_and_unconfigured_writes_disabled(self):
        body = encode_manifest([self.first])
        self.assertEqual(self.push(body, 'different').code, 401)
        self.assertEqual(self.fetch('/v1/trust/manifest', method='POST', body=body).code, 401)
        self._app.settings['trust_api_key'] = ''
        self.assertEqual(self.push(body).code, 401)
        self.assertFalse(self.db.exists())

    def test_replays_and_stale_snapshots_do_not_remove_builds(self):
        for rows in ([self.first, self.rebuilt], [self.first, self.second], [self.first], []):
            self.assertEqual(self.push(encode_manifest(rows)).code, 204)
        expected = [self.first, self.rebuilt, self.second]
        self.assertEqual(parse_manifest(self.fetch('/auth.json').body), expected)
        self.assertEqual(parse_manifest(snapshot(self.db)), expected)
        self.assertEqual(self.fetch('/').body, self.fetch('/index.html').body)
        self.assertIn(b'./auth.json', self.fetch('/').body)

    def test_invalid_manifest_is_rejected_as_a_whole(self):
        for bad in (b'not-json', b'[]', b'{"schema":true,"entries":[]}',
                    encode_manifest([self.first, ('v2', 'arm', 'bad')]),
                    json.dumps({'schema': 1, 'entries': [None]}).encode()):
            self.assertEqual(self.push(bad).code, 400)
        self.assertEqual(parse_manifest(self.fetch('/auth.json').body), [])
