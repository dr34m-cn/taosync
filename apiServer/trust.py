import asyncio
import hmac
import sqlite3
from contextlib import closing
from pathlib import Path

import tornado.web

if __package__:
    from .trust_manifest import MAX_MANIFEST_BYTES, encode_manifest, parse_builds, split_builds
else:  # Standalone apiServer Docker image
    from trust_manifest import MAX_MANIFEST_BYTES, encode_manifest, parse_builds, split_builds


def snapshot(database, incoming=None, kind='stable'):
    if kind not in ('stable', 'dev', 'latest'):
        raise ValueError('invalid manifest kind')
    with closing(sqlite3.connect(database, timeout=15)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS builds (version TEXT, arch TEXT, sha256 TEXT, '
                   'UNIQUE(version, arch, sha256))')
        if 'published_at' not in {col[1] for col in db.execute('PRAGMA table_info(builds)')}:
            db.execute('ALTER TABLE builds ADD COLUMN published_at TEXT')
        if incoming is not None:
            db.executemany('INSERT INTO builds (version, arch, sha256, published_at) VALUES (?, ?, ?, ?) '
                           'ON CONFLICT(version, arch, sha256) DO UPDATE SET published_at=excluded.published_at '
                           'WHERE builds.published_at IS NULL', parse_builds(incoming))
        rows = db.execute('SELECT version, arch, sha256, published_at FROM builds ORDER BY rowid').fetchall()
        stable, dev, latest_version, latest = split_builds(rows)
        # Check every manifest's size before committing writes: never serve a truncated list.
        if incoming is not None:
            encoded = {
                'stable': encode_manifest(stable),
                'dev': encode_manifest(dev),
                'latest': encode_manifest(latest, version=latest_version),
            }
            return encoded[kind]
        if kind == 'stable':
            return encode_manifest(stable)
        if kind == 'dev':
            return encode_manifest(dev)
        return encode_manifest(latest, version=latest_version)


class TrustIndex(tornado.web.RequestHandler):
    def get(self):
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        self.set_header('X-Content-Type-Options', 'nosniff')
        self.finish(Path(__file__).with_name('index.html').read_bytes())


class PublicManifest(tornado.web.RequestHandler):
    def initialize(self, kind='stable'):
        self.kind = kind

    async def get(self):
        raw = await asyncio.to_thread(snapshot, self.settings['trust_database'], kind=self.kind)
        self.set_header('Cache-Control', 'no-store')
        self.set_header('Content-Type', 'application/json; charset=utf-8')
        self.finish(raw)


@tornado.web.stream_request_body
class TrustPush(tornado.web.RequestHandler):
    def prepare(self):
        expected = self.settings['trust_api_key']
        supplied = self.request.headers.get('Authorization', '')
        if not expected or not hmac.compare_digest(supplied.encode(), ('Bearer ' + expected).encode()):
            raise tornado.web.HTTPError(401)
        if self.request.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise tornado.web.HTTPError(415)
        raw_length = self.request.headers.get('Content-Length')
        if raw_length is not None:
            try:
                length = int(raw_length)
            except ValueError:
                raise tornado.web.HTTPError(400) from None
            if length < 0:
                raise tornado.web.HTTPError(400)
            if length > MAX_MANIFEST_BYTES:
                raise tornado.web.HTTPError(413)
        self.request.connection.set_max_body_size(MAX_MANIFEST_BYTES)
        self.body = bytearray()

    def data_received(self, chunk):
        if len(self.body) + len(chunk) > MAX_MANIFEST_BYTES:
            raise tornado.web.HTTPError(413)
        self.body.extend(chunk)

    async def post(self):
        try:
            await asyncio.to_thread(snapshot, self.settings['trust_database'], self.body)
        except ValueError:
            raise tornado.web.HTTPError(400)
        self.set_status(204)
        self.finish()
