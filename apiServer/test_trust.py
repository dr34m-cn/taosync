import json
import sqlite3
from contextlib import closing
import tempfile
from pathlib import Path

from tornado.testing import AsyncHTTPTestCase

try:
    from .app import make_app
    from .trust import snapshot
    from .trust_manifest import (
        encode_manifest,
        parse_builds,
        parse_download_sources,
        parse_latest,
        parse_latest_details,
        parse_manifest,
    )
except ImportError:  # pragma: no cover - unittest discovery may import this as a script module
    from app import make_app
    from trust import snapshot
    from trust_manifest import (
        encode_manifest,
        parse_builds,
        parse_download_sources,
        parse_latest,
        parse_latest_details,
        parse_manifest,
    )


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

    def test_latest_downloads_enforces_retention_channel_sources_and_dynamic_updates(self):
        rows = [
            ('v0.5.0', 'linux-amd64', '1' * 64, '2026-11-10T00:00:00Z'),
            ('v0.5.1', 'linux-amd64', '2' * 64, '2026-11-12T00:00:00Z'),
            ('v0.5.2', 'linux-amd64', '3' * 64, '2026-11-14T00:00:00Z'),
            ('v0.5.2', 'windows-amd64', '4' * 64, '2026-11-14T00:00:00Z'),
            ('v0.5.3', 'linux-amd64', '5' * 64, '2026-11-16T00:00:00Z'),
            ('v0.5.3', 'linux-StaticX-amd64', '6' * 64, '2026-11-16T00:00:00Z'),
            ('v0.5.4-dev-build1', 'linux-amd64', '7' * 64, '2026-11-17T00:00:00Z'),
            ('v0.5.4-beta.1', 'linux-amd64', '8' * 64, '2026-11-18T00:00:00Z'),
            ('v0.5.4-pre-build2', 'linux-amd64', '9' * 64, '2026-11-19T00:00:00Z'),
        ]
        self.assertEqual(self.push(encode_manifest(rows)).code, 204)
        version, entries, downloads = parse_latest_details(self.fetch('/latest.json').body)
        self.assertEqual(version, 'v0.5.3')
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            [(item['version'], item['channel']) for item in downloads['versions']],
            [
                ('v0.5.3', 'stable'),
                ('v0.5.2', 'stable'),
                ('v0.5.1', 'stable'),
                ('v0.5.4-pre-build2', 'dev'),
                ('v0.5.4-beta.1', 'dev'),
            ],
        )
        stable_item = downloads['versions'][0]
        self.assertEqual([src['id'] for src in stable_item['sources']], ['github', 'r2'])
        self.assertEqual(stable_item['assets'], {
            'linux-StaticX-amd64': 'taoSync-v0.5.3-linux-StaticX-amd64.zip',
            'linux-amd64': 'taoSync-v0.5.3-linux-amd64.tar.gz',
        })
        dev_item = downloads['versions'][3]
        self.assertEqual([src['id'] for src in dev_item['sources']], ['r2'])
        self.assertEqual(dev_item['assets'], {'linux-amd64': 'taoSync-v0.5.4-pre-build2-linux-amd64.tar.gz'})

        # Push updated source list dynamically without changing client or server code.
        custom_sources = {
            'stable': [
                {'id': 'r2', 'name': 'Cloudflare R2', 'urlTemplate': 'https://cdn.20240303.xyz/taosync-release/{version}/{filename}'},
                {'id': 'mirror', 'name': 'Custom Mirror', 'labels': {'zh-CN': '备用镜像', 'en': 'Backup Mirror'},
                 'urlTemplate': 'https://mirror.example.com/releases/{version}/{filename}'},
                {'id': 'github', 'name': 'GitHub Release', 'urlTemplate': 'https://github.com/dr34m-cn/taosync/releases/download/{version}/{filename}'},
            ],
            'dev': [
                {'id': 'r2', 'name': 'Cloudflare R2', 'urlTemplate': 'https://cdn.20240303.xyz/taosync-release/dev/{version}/{filename}'},
                {'id': 'dev-mirror', 'name': 'Dev Mirror', 'urlTemplate': 'https://dev.example.com/{version}/{filename}'},
            ],
        }
        self.assertEqual(self.push(encode_manifest([], download_sources=custom_sources)).code, 204)
        # Re-pushing legacy payload without downloadSources keeps stored sources intact.
        self.assertEqual(self.push(encode_manifest([])).code, 204)
        _, _, updated_downloads = parse_latest_details(self.fetch('/latest.json').body)
        self.assertEqual([src['id'] for src in updated_downloads['versions'][0]['sources']], ['r2', 'mirror', 'github'])
        self.assertEqual([src['id'] for src in updated_downloads['versions'][3]['sources']], ['r2', 'dev-mirror'])
        self.assertEqual(parse_download_sources(self.fetch('/auth.json').body)['stable'][1]['labels']['zh-CN'], '备用镜像')

        # Invalid downloadSources payloads must be rejected atomically.
        for bad_sources in (
            {'stable': [{'id': 'auto', 'name': 'Reserved', 'urlTemplate': 'https://a.example/{filename}'}], 'dev': []},
            {'stable': [{'id': 'http', 'name': 'Insecure', 'urlTemplate': 'http://a.example/{filename}'}], 'dev': []},
            {'stable': [{'id': 'bad', 'name': 'Missing Placeholder', 'urlTemplate': 'https://a.example/static.zip'}], 'dev': []},
        ):
            payload = json.dumps({'schema': 1, 'entries': [], 'downloadSources': bad_sources}).encode('utf-8')
            self.assertEqual(self.push(payload).code, 400)
