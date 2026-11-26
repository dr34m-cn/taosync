"""Complete directory listings. Cloud parent IDs reconcile cache edits, never authorize I/O."""

import json
import posixpath
import sqlite3
import threading
import time
from contextvars import ContextVar

from common import sqlBase


source_listing = ContextVar('source_listing', default=False)
cloud_listing = ContextVar('cloud_listing', default=None)
SCHEMA = ('create table if not exists storage_directory_cache('
          'mountId integer not null, path text not null, scanned real not null, '
          'strict integer not null, sourceReady integer not null, entries text not null, cloud text, folderId text, '
          'primary key(mountId,path)) without rowid')


class DirectoryCache:
    def __init__(self, persistent=False):
        self.lock = threading.RLock()
        self.revision = 0
        self.persistent = persistent
        if not persistent:
            self.db = sqlite3.connect(':memory:', check_same_thread=False)
            self.db.execute(SCHEMA)

    def _run(self, mount, action):
        def transact(conn):
            days = mount.get('cacheDays', 30)
            if self.persistent:
                row = conn.execute('select cacheDays,cacheEpoch from storage_mount where id=?',
                                   (mount['id'],)).fetchone()
                if not row or row[1] != mount.get('cacheEpoch', 1):
                    return None
                days = row[0]
            if days != 0:
                with conn:
                    return action(conn, days)
        with self.lock:
            return sqlBase.connect_sql(transact)() if self.persistent else transact(self.db)

    def read(self, mount, path, strict=False, source=False):
        def action(conn, days):
            row = conn.execute('select scanned,strict,sourceReady,entries from storage_directory_cache '
                               'where mountId=? and path=?', (mount['id'], path)).fetchone()
            if row is None:
                return None
            if days > 0 and time.time() - row[0] >= days * 86400:
                conn.execute('delete from storage_directory_cache where mountId=? and path=?', (mount['id'], path))
                return None
            if (not strict or row[1]) and (not source or row[2]):
                return json.loads(row[3])
        return self._run(mount, action)

    def record(self, mount, path, entries, strict, revision, identity=None):
        def action(conn, days):
            if self.revision == revision:
                conn.execute('insert or replace into storage_directory_cache values(?,?,?,?,?,?,?,?)',
                             (mount['id'], path, time.time(), strict, 1, json.dumps(entries, ensure_ascii=False),
                              *(identity or (None, None))))
        self._run(mount, action)

    def cloudAliasPath(self, source, path, other):
        """Map different roots on a known shared drive using previously listed folders, without I/O to the drive."""
        def locate(conn):
            def path_of(mount, folder):
                row = conn.execute('select path from storage_directory_cache where mountId=? and folderId=? limit 1',
                                   (mount['id'], folder)).fetchone()
                return row[0] if row else None

            def relative(parent, child):
                if child == parent or parent.startswith(child.rstrip('/') + '/'):
                    return '/'
                prefix = parent.rstrip('/') + '/'
                return '/' + child[len(prefix):] if child.startswith(prefix) else None

            root = path_of(source, other['config'].get('root_folder_id') or 'root')
            if root is not None:
                return relative(root, path)
            root = path_of(other, source['config'].get('root_folder_id') or 'root')
            if root is not None:
                return posixpath.join(root, path.lstrip('/'))
            # Two independently listed subtrees can intersect even if their roots were never scanned.
            at = path
            while at != '/':
                row = conn.execute('select b.path from storage_directory_cache a join storage_directory_cache b '
                                   'on a.cloud=b.cloud and a.folderId=b.folderId where a.mountId=? and a.path=? '
                                   'and b.mountId=? limit 1', (source['id'], at, other['id'])).fetchone()
                if row:
                    return posixpath.join(row[0], path[len(at):].strip('/')).rstrip('/') or '/'
                at = posixpath.dirname(at)
            return '/'  # No reliable mapping: do not return a potentially stale alias.
        with self.lock:
            return sqlBase.connect_sql(locate)() if self.persistent else locate(self.db)

    def cloudMkdir(self, cloud, folderId, name):
        # Match actual listed parent IDs across aliases. Draft picker paths are not authoritative.
        @sqlBase.connect_sql
        def patch(conn):
            rows = conn.execute('select c.mountId,c.path,m.cacheEpoch from storage_directory_cache c '
                                'join storage_mount m on c.mountId=m.id where c.cloud=? and c.folderId=?',
                                (cloud, folderId)).fetchall()
            for mid, path, epoch in rows:
                self.change({'id': mid, 'cacheEpoch': epoch}, posixpath.join(path, name), 'directory')
        with self.lock:
            self.revision += 1
            patch()

    def change(self, mount, path, kind, size=None):
        """Patch only an already-listed parent. Never mark a partial listing as complete."""
        def action(conn, days):
            mid = mount['id']
            self.revision += 1

            def forget_subtree(prefix):
                if prefix == '/':
                    conn.execute('delete from storage_directory_cache where mountId=?', (mid,))
                else:
                    base = prefix + '/'
                    conn.execute('delete from storage_directory_cache where mountId=? and '
                                 '(path=? or (path>=? and path<?))', (mid, prefix, base, prefix + '0'))

            def patch(parent, name, change):
                row = conn.execute('select entries from storage_directory_cache where mountId=? and path=?',
                                   (mid, parent)).fetchone()
                if row is None:
                    return
                entries = json.loads(row[0])
                matches = [item for item in entries if item['name'] == name]
                if change == 'directory' and len(matches) == 1 and matches[0]['is_dir']:
                    return
                entries = [item for item in entries if item['name'] != name]
                if change != 'delete':
                    folder = change == 'directory'
                    entries.append({'name': name, 'is_dir': folder, 'size': None if folder else size})
                entries.sort(key=lambda item: (not item['is_dir'], item['name'].casefold()))
                conn.execute('update storage_directory_cache set entries=?, '
                             'sourceReady=case when ? then 0 else sourceReady end where mountId=? and path=?',
                             (json.dumps(entries, ensure_ascii=False), change == 'file', mid, parent))

            if path == '/':
                forget_subtree(path)
                return
            parent, name = posixpath.split(path)
            if kind != 'directory':
                forget_subtree(path)
            if kind == 'unknown':
                conn.execute('delete from storage_directory_cache where mountId=? and path=?', (mid, parent))
                return
            patch(parent, name, kind)
            if kind != 'delete':
                # mkdir and uploads may have created missing ancestors along the way.
                while parent != '/':
                    parent, name = posixpath.split(parent)
                    patch(parent, name, 'directory')
        self._run(mount, action)


storedListings = DirectoryCache(persistent=True)
