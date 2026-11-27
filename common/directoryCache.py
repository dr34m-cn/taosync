"""Complete directory listings. Cloud parent IDs reconcile cache edits, never authorize I/O."""

import json
import posixpath
import sqlite3
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

from common import sqlBase


source_listing = ContextVar('source_listing', default=False)
cloud_listing = ContextVar('cloud_listing', default=None)
SCHEMA = ('create table if not exists storage_directory_cache('
          'mountId integer not null, path text not null, scanned real not null, '
          'strict integer not null, sourceReady integer not null, entries text not null, cloud text, folderId text, '
          'primary key(mountId,path)) without rowid')


def _norm(path):
    return path.rstrip('/') or '/'


class DirectoryCache:
    def __init__(self, persistent=False):
        self.lock = threading.RLock()
        self.revision = 0
        self._active = []
        self.persistent = persistent
        if not persistent:
            self.db = sqlite3.connect(':memory:', check_same_thread=False)
            self.db.execute(SCHEMA)

    @contextmanager
    def scan(self, mount, path):
        token = [mount['id'], _norm(path), False]
        with self.lock:
            self._active.append(token)
        try:
            yield token
        finally:
            with self.lock:
                try:
                    self._active.remove(token)
                except ValueError:
                    pass

    def _invalidate_active(self, mid, path, kind):
        if path == '/':
            for token in self._active:
                if token[0] == mid:
                    token[2] = True
            return
        parent, _ = posixpath.split(path)
        prefix = path + '/'
        for token in self._active:
            if token[0] != mid:
                continue
            active_path = token[1]
            if active_path == parent:
                token[2] = True
            elif kind != 'directory' and (active_path == path or active_path.startswith(prefix)):
                token[2] = True
            elif kind != 'delete' and parent.startswith(active_path.rstrip('/') + '/'):
                token[2] = True

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
        path = _norm(path)
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
        path = _norm(path)
        def action(conn, days):
            fresh = self.revision == revision if isinstance(revision, int) else not revision[2]
            if fresh:
                conn.execute('insert or replace into storage_directory_cache values(?,?,?,?,?,?,?,?)',
                             (mount['id'], path, time.time(), strict, 1, json.dumps(entries, ensure_ascii=False),
                              *(identity or (None, None))))
        self._run(mount, action)

    def cloudAliasPath(self, source, path, other):
        """Map different roots on a known shared drive using previously listed folders, without I/O to the drive."""
        path = _norm(path)
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
                return posixpath.join(root, path.lstrip('/')).rstrip('/') or '/'
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
        def find_affected(conn):
            if not self.persistent:
                rows = conn.execute('select mountId,path,1 from storage_directory_cache '
                                    'where cloud=? and folderId=?', (cloud, folderId)).fetchall()
                return rows, []
            rows = conn.execute('select c.mountId,c.path,m.cacheEpoch from storage_directory_cache c '
                                'join storage_mount m on c.mountId=m.id where c.cloud=? and c.folderId=?',
                                (cloud, folderId)).fetchall()
            crypt_rows = []
            if rows:
                mount_ids = sorted({mid for mid, _, _ in rows})
                placeholders = ','.join('?' for _ in mount_ids)
                crypt_rows = conn.execute(
                    f"select id,cacheEpoch,config from storage_mount where driverType='crypt' "
                    f"and json_extract(config,'$.target_mount_id') in ({placeholders})",
                    mount_ids,
                ).fetchall()
            return rows, crypt_rows

        with self.lock:
            self.revision += 1
            for token in self._active:
                token[2] = True
            rows, crypt_rows = sqlBase.connect_sql(find_affected)() if self.persistent else find_affected(self.db)
            created_by_mount = {}
            for mid, path, epoch in rows:
                created = _norm(posixpath.join(path, name))
                created_by_mount.setdefault(mid, []).append(created)
                self.change({'id': mid, 'cacheEpoch': epoch}, created, 'directory')
            if crypt_rows:
                from service.storage.pathIdentity import virtual_paths_overlap
                for cid, cepoch, raw_cfg in crypt_rows:
                    try:
                        cfg = json.loads(raw_cfg or '{}')
                    except (TypeError, ValueError):
                        continue
                    base = cfg.get('target_path', '/')
                    if any(virtual_paths_overlap(created, base, case_sensitive=False)
                           for created in created_by_mount.get(cfg.get('target_mount_id'), ())):
                        self.change({'id': cid, 'cacheEpoch': cepoch}, '/', 'unknown')

    def change(self, mount, path, kind, size=None):
        """Patch only an already-listed parent. Never mark a partial listing as complete."""
        path = _norm(path)
        def action(conn, days):
            mid = mount['id']
            self.revision += 1
            self._invalidate_active(mid, path, kind)

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
                if any(item['name'] != name and item['name'].casefold() == name.casefold() for item in entries):
                    # Case-only collisions behave differently across filesystems; re-list cleanly.
                    conn.execute('delete from storage_directory_cache where mountId=? and path=?', (mid, parent))
                    return
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
