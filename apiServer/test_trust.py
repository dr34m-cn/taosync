import json
import sqlite3
from contextlib import closing
import tempfile
from pathlib import Path

from tornado.testing import AsyncHTTPTestCase

try:
    from .app import make_app
    from .trust import snapshot
    from .trust_manifest import encode_manifest, parse_builds, parse_latest, parse_manifest
except ImportError:  # pragma: no cover - unittest discovery may import this as a script module
    from app import make_app
    from trust import snapshot
    from trust_manifest import encode_manifest, parse_builds, parse_latest, parse_manifest


class TrustServiceTest(AsyncHTTPTestCase):
    key = 'service-test-only-' * 3
    first = ('v0.5.1-dev', 'linux-amd64', 'a' * 64)
    rebuilt = ('v0.5.1-dev', 'linux-amd64', 'b' * 64)
    second = ('v0.5.1-pre', 'linux-arm64', 'c' * 64)
    stable_old = ('v0.5.2', 'linux-amd64', 'd' * 64)
    stable_new_a = ('v0.5.10', 'linux-amd64', 'e' * 64)
    stable_new_b = ('v0.5.10', 'windows-amd64', 'f' * 64)

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

    def test_replays_and_stale_snapshots_split_stable_dev_and_latest(self):
        for rows in (
            [self.first, self.rebuilt, self.stable_old],
            [self.first, self.second, self.stable_new_a, self.stable_new_b],
            [self.first],
            [],
        ):
            self.assertEqual(self.push(encode_manifest(rows)).code, 204)
        expected_stable = [self.stable_old, self.stable_new_a, self.stable_new_b]
        expected_dev = [self.first, self.rebuilt, self.second]
        expected_latest = [self.stable_new_a, self.stable_new_b]
        self.assertEqual(parse_manifest(self.fetch('/auth.json').body), expected_stable)
        self.assertEqual(parse_manifest(snapshot(self.db, kind='stable')), expected_stable)
        self.assertEqual(parse_manifest(self.fetch('/auth-dev.json').body), expected_dev)
        self.assertEqual(parse_manifest(snapshot(self.db, kind='dev')), expected_dev)
        self.assertEqual(parse_latest(self.fetch('/latest.json').body), ('v0.5.10', expected_latest))
        self.assertEqual(parse_latest(snapshot(self.db, kind='latest')), ('v0.5.10', expected_latest))
        index = self.fetch('/').body
        self.assertEqual(index, self.fetch('/index.html').body)
        for link in (b'./auth.json', b'./auth-dev.json', b'./latest.json'):
            self.assertIn(link, index)

    def test_dev_only_registry_keeps_stable_and_latest_empty(self):
        self.assertEqual(self.push(encode_manifest([self.first, self.second])).code, 204)
        self.assertEqual(parse_manifest(self.fetch('/auth.json').body), [])
        self.assertEqual(parse_latest(self.fetch('/latest.json').body), (None, []))
        self.assertEqual(parse_manifest(self.fetch('/auth-dev.json').body), [self.first, self.second])

    def test_invalid_manifest_is_rejected_as_a_whole(self):
        for bad in (b'not-json', b'[]', b'{"schema":true,"entries":[]}',
                    encode_manifest([self.first, ('v2', 'arm', 'bad')]),
                    json.dumps({'schema': 1, 'entries': [None]}).encode()):
            self.assertEqual(self.push(bad).code, 400)
        self.assertEqual(parse_manifest(self.fetch('/auth.json').body), [])
        self.assertEqual(parse_manifest(self.fetch('/auth-dev.json').body), [])
        self.assertEqual(parse_latest(self.fetch('/latest.json').body), (None, []))

    def test_legacy_registry_keeps_first_publication_date(self):
        stamp = '2026-11-20T09:54:33Z'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE builds (version TEXT, arch TEXT, sha256 TEXT, UNIQUE(version, arch, sha256))')
            db.execute('INSERT INTO builds VALUES (?, ?, ?)', self.first)
            db.execute('INSERT INTO builds VALUES (?, ?, ?)', self.stable_old)
        for row in ((*self.first, stamp), self.first, (*self.first, '2026-11-21T08:00:00Z'),
                    (*self.stable_old, stamp), (*self.stable_old, '2026-11-21T08:00:00Z')):
            self.assertEqual(self.push(encode_manifest([row])).code, 204)
        self.assertEqual(parse_builds(self.fetch('/auth-dev.json').body), [(*self.first, stamp)])
        self.assertEqual(parse_builds(self.fetch('/auth.json').body), [(*self.stable_old, stamp)])
        self.assertEqual(parse_builds(self.fetch('/latest.json').body), [(*self.stable_old, stamp)])
        self.assertEqual(self.fetch('/logo.ico').body, Path(__file__).resolve().parents[1].joinpath('logo.ico').read_bytes())
