"""Anonymous counters for one apiServer process. No per-report records."""
import asyncio
import json
import logging
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import tornado.web


class SyncTotals:
    def __init__(self, database):
        self.database = database
        self.lock = threading.Lock()
        self.writer = threading.Lock()
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database, timeout=15)) as db, db:
            # Decimal text also preserves totals beyond SQLite's signed 64-bit range.
            db.execute('CREATE TABLE IF NOT EXISTS totals (id INTEGER PRIMARY KEY CHECK(id=1), files TEXT NOT NULL, bytes TEXT NOT NULL)')
            db.execute("INSERT OR IGNORE INTO totals VALUES (1, '0', '0')")
            self.saved = tuple(map(int, db.execute('SELECT files, bytes FROM totals WHERE id=1').fetchone()))
        self.total = self.saved

    def add(self, files, size):
        with self.lock:
            self.total = (self.total[0] + files, self.total[1] + size)

    def snapshot(self):
        with self.lock:
            return self.total

    def flush(self):
        # Do not hold the hot-path lock during disk I/O. On failure saved stays unchanged.
        with self.writer:
            snapshot = self.snapshot()
            if snapshot != self.saved:
                with closing(sqlite3.connect(self.database, timeout=15)) as db, db:
                    db.execute('UPDATE totals SET files=?, bytes=? WHERE id=1', tuple(map(str, snapshot)))
                self.saved = snapshot

    async def checkpoint(self):
        await asyncio.to_thread(self.flush)


class PublicApplication(tornado.web.Application):
    def log_request(self, handler):
        if not isinstance(handler, StatsHandler):
            super().log_request(handler)


@tornado.web.stream_request_body
class StatsHandler(tornado.web.RequestHandler):
    def log_exception(self, typ, value, tb):
        if self.request.method != 'POST' and not isinstance(value, tornado.web.HTTPError):
            logging.error('Anonymous statistics request failed')

    def prepare(self):
        self.set_header('Cache-Control', 'no-store')
        self.body = bytearray()
        if self.request.query:
            raise tornado.web.HTTPError(400)
        if self.request.method == 'POST':
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
                if length > 256:
                    raise tornado.web.HTTPError(413)
        self.request.connection.set_max_body_size(256)

    def data_received(self, chunk):
        if len(self.body) + len(chunk) > 256:
            raise tornado.web.HTTPError(413)
        self.body.extend(chunk)

    def get(self):
        self.set_header('Access-Control-Allow-Origin', '*')
        files, size = self.settings['sync_totals'].snapshot()
        self.write({'files': str(files), 'bytes': str(size)})

    def post(self):
        try:
            obj = json.loads(self.body)
            if (not isinstance(obj, dict) or obj.keys() != {'files', 'bytes'}
                    or any(type(v) is not int or not 0 <= v <= 2**63 - 1 for v in obj.values())
                    or (not obj['files'] and obj['bytes'])):
                raise ValueError
        except (ValueError, RecursionError):
            raise tornado.web.HTTPError(400) from None
        self.settings['sync_totals'].add(obj['files'], obj['bytes'])
        self.set_status(204)
        self.finish()
