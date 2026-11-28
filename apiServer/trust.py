import asyncio
import hmac
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import tornado.web

if __package__:
    from .trust_manifest import (
        MAX_MANIFEST_BYTES,
        build_downloads_catalog,
        encode_manifest,
        load_download_sources,
        normalize_download_sources,
        normalize_version_sources,
        parse_builds,
        parse_download_sources,
        parse_version_sources,
        split_builds,
    )
else:  # Standalone apiServer Docker image
    from trust_manifest import (
        MAX_MANIFEST_BYTES,
        build_downloads_catalog,
        encode_manifest,
        load_download_sources,
        normalize_download_sources,
        normalize_version_sources,
        parse_builds,
        parse_download_sources,
        parse_version_sources,
        split_builds,
    )


def snapshot(database, incoming=None, kind='stable', default_sources=None):
    if kind not in ('stable', 'dev', 'latest'):
        raise ValueError('invalid manifest kind')
    with closing(sqlite3.connect(database, timeout=15)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS builds (version TEXT, arch TEXT, sha256 TEXT, '
                   'UNIQUE(version, arch, sha256))')
        db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
        if 'published_at' not in {col[1] for col in db.execute('PRAGMA table_info(builds)')}:
            db.execute('ALTER TABLE builds ADD COLUMN published_at TEXT')
        if incoming is not None:
            parsed_rows = parse_builds(incoming)
            incoming_sources = parse_download_sources(incoming)
            incoming_version_sources = parse_version_sources(incoming)
            db.executemany('INSERT INTO builds (version, arch, sha256, published_at) VALUES (?, ?, ?, ?) '
                           'ON CONFLICT(version, arch, sha256) DO UPDATE SET published_at=excluded.published_at '
                           'WHERE builds.published_at IS NULL', parsed_rows)
            if incoming_sources is not None:
                db.execute(
                    'INSERT INTO metadata (key, value) VALUES (?, ?) '
                    'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    ('download_sources', json.dumps(incoming_sources, ensure_ascii=False)),
                )
            if incoming_version_sources is not None:
                db.execute(
                    'INSERT INTO metadata (key, value) VALUES (?, ?) '
                    'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    ('version_sources', json.dumps(incoming_version_sources, ensure_ascii=False)),
                )
        row = db.execute('SELECT value FROM metadata WHERE key = ?', ('download_sources',)).fetchone()
        if row is not None:
            sources = normalize_download_sources(json.loads(row[0]))
        else:
            sources = normalize_download_sources(default_sources) if default_sources is not None else load_download_sources()
        version_sources_row = db.execute('SELECT value FROM metadata WHERE key = ?', ('version_sources',)).fetchone()
        version_sources = (
            normalize_version_sources(json.loads(version_sources_row[0]))
            if version_sources_row is not None
            else None
        )
        rows = db.execute('SELECT version, arch, sha256, published_at FROM builds ORDER BY rowid').fetchall()
        stable, dev, latest_version, latest = split_builds(rows)
        downloads = build_downloads_catalog(stable, dev, sources, version_sources=version_sources)
        # Check every manifest's size before committing writes: never serve a truncated list.
        if incoming is not None:
            encoded = {
                'stable': encode_manifest(stable, download_sources=sources, version_sources=version_sources),
                'dev': encode_manifest(dev, download_sources=sources, version_sources=version_sources),
                'latest': encode_manifest(latest, version=latest_version, downloads=downloads),
            }
            return encoded[kind]
        if kind == 'stable':
            return encode_manifest(stable, download_sources=sources, version_sources=version_sources)
        if kind == 'dev':
            return encode_manifest(dev, download_sources=sources, version_sources=version_sources)
        return encode_manifest(latest, version=latest_version, downloads=downloads)


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
