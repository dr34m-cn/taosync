"""Minimal fake OpenList/AList server backed by local directories, with fault injection."""
import asyncio
import json
import os
import shutil
import socket
import threading
import time
import uuid

import tornado.web


class FakeAlist:
    def __init__(self):
        self.storages = {}      # mount_path -> {'root': dir, 'driver': 'Local'|'189Cloud', 'dirSizeDelay': s}
        self.tasks = {}
        self.lock = threading.Lock()
        self.listCalls = []     # (path, refresh)
        self.copyFaults = []    # dict(dst_prefix, name_match, mode: 'fail'|'write_then_fail'|'truncate')
        self.port = None

    # -------------------------------------------------- path mapping
    def storage(self, mount, root, driver='Local', dirSizeDelay=0.0):
        os.makedirs(root, exist_ok=True)
        self.storages[mount.rstrip('/')] = {'root': root, 'driver': driver, 'dirSizeDelay': dirSizeDelay}

    def resolve(self, path):
        path = '/' + path.strip('/')
        best = None
        for mount in self.storages:
            if path == mount or path.startswith(mount + '/'):
                if best is None or len(mount) > len(best):
                    best = mount
        if best is None:
            raise FileNotFoundError(path)
        rel = path[len(best):].strip('/')
        info = self.storages[best]
        return info, os.path.join(info['root'], *rel.split('/')) if rel else info['root']

    # -------------------------------------------------- operations
    def list(self, path, refresh):
        with self.lock:
            self.listCalls.append((path, refresh))
        if '/' + path.strip('/') == '/':
            return [{'name': m.strip('/'), 'is_dir': True, 'size': 0, 'modified': '', 'hash_info': None}
                    for m in self.storages]
        info, real = self.resolve(path)
        if refresh and info['dirSizeDelay']:
            time.sleep(info['dirSizeDelay'])   # OpenList Local + directory_size: RecalculateDirSize()
        if not os.path.isdir(real):
            raise FileNotFoundError('object not found')
        out = []
        for entry in os.scandir(real):
            st = entry.stat()
            out.append({'name': entry.name, 'is_dir': entry.is_dir(), 'size': 0 if entry.is_dir() else st.st_size,
                        'modified': str(st.st_mtime_ns), 'hash_info': None})
        return out

    def copy(self, srcDir, dstDir, name):
        tid = uuid.uuid4().hex[:12]
        task = {'id': tid, 'state': 0, 'progress': 0, 'error': ''}
        with self.lock:
            self.tasks[tid] = task

        def run():
            task['state'] = 1
            time.sleep(0.05)
            try:
                _, src = self.resolve(srcDir.rstrip('/') + '/' + name)
                _, dstParent = self.resolve(dstDir)
                fault = next((f for f in self.copyFaults if dstDir.startswith(f['dst_prefix'])
                              and f['match'](name)), None)
                if fault and fault['mode'] == 'fail':
                    raise IOError('upload failed: remote rejected')
                os.makedirs(dstParent, exist_ok=True)
                target = os.path.join(dstParent, name)
                if fault and fault['mode'] == 'truncate':
                    with open(src, 'rb') as s, open(target, 'wb') as d:
                        d.write(s.read()[: max(0, os.path.getsize(src) // 2)])
                else:
                    shutil.copyfile(src, target)
                if fault and fault['mode'] == 'write_then_fail':
                    raise ValueError('parsing time "Aug 28, 2026, 10:00:35\\xe2\\x80\\xafPM +08" as '
                                     '"Jan 2, 2006 15:04:05 PM -07": cannot parse ", 10:00:35\\xe2\\x80\\xafPM +08" as " "')
                task['progress'] = 100
                task['state'] = 2
            except Exception as exc:
                task['error'] = str(exc)
                task['state'] = 7

        threading.Thread(target=run, daemon=True).start()
        return tid

    # -------------------------------------------------- http
    def start(self):
        fake = self

        class Base(tornado.web.RequestHandler):
            def ok(self, data=None):
                self.write(json.dumps({'code': 200, 'message': 'success', 'data': data}))

            def fail(self, code, msg):
                self.write(json.dumps({'code': code, 'message': msg, 'data': None}))

            def body(self):
                return json.loads(self.request.body or b'{}')

        class Me(Base):
            def get(self):
                self.ok({'username': 'admin'})

        class FsList(Base):
            def post(self):
                b = self.body()
                try:
                    self.ok({'content': fake.list(b['path'], b.get('refresh', False)), 'total': 0})
                except FileNotFoundError as exc:
                    self.fail(500, str(exc))

        class Mkdir(Base):
            def post(self):
                _, real = fake.resolve(self.body()['path'])
                os.makedirs(real, exist_ok=True)
                self.ok()

        class Remove(Base):
            def post(self):
                b = self.body()
                for name in b['names']:
                    _, real = fake.resolve(b['dir'].rstrip('/') + '/' + name)
                    if os.path.isdir(real):
                        shutil.rmtree(real)
                    elif os.path.exists(real):
                        os.remove(real)
                self.ok()

        class Copy(Base):
            def post(self):
                b = self.body()
                tasks = [{'id': fake.copy(b['src_dir'], b['dst_dir'], n)} for n in b['names']]
                self.ok({'tasks': tasks})

        class TaskInfo(Base):
            def post(self):
                task = fake.tasks.get(self.get_argument('tid'))
                if task is None:
                    self.fail(404, 'task not found')
                else:
                    self.ok(dict(task))

        class TaskDrop(Base):
            def post(self):
                fake.tasks.pop(self.get_argument('tid'), None)
                self.ok()

        class TaskCancel(Base):
            def post(self):
                task = fake.tasks.get(self.get_argument('tid'))
                if task and task['state'] in (0, 1):
                    task['state'] = 4
                self.ok()

        class StorageList(Base):
            def get(self):
                self.ok({'content': [{'id': i + 1, 'mount_path': m, 'driver': s['driver'], 'disabled': False}
                                     for i, (m, s) in enumerate(fake.storages.items())],
                         'total': len(fake.storages)})

        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        self.port = sock.getsockname()[1]
        sock.close()
        ready = threading.Event()

        def serve():
            asyncio.set_event_loop(asyncio.new_event_loop())
            app = tornado.web.Application([
                (r'/api/me', Me), (r'/api/fs/list', FsList), (r'/api/fs/mkdir', Mkdir),
                (r'/api/fs/remove', Remove), (r'/api/fs/copy', Copy),
                (r'/api/admin/task/copy/info', TaskInfo), (r'/api/admin/task/copy/delete', TaskDrop),
                (r'/api/admin/task/copy/cancel', TaskCancel), (r'/api/admin/storage/list', StorageList),
            ])
            app.listen(self.port, address='127.0.0.1')
            ready.set()
            asyncio.get_event_loop().run_forever()

        threading.Thread(target=serve, daemon=True).start()
        ready.wait(5)
        return 'http://127.0.0.1:%d' % self.port
