import posixpath
import threading
from contextvars import ContextVar


scanning_child = ContextVar('scanning_child', default=False)


class ScanState:
    """Raw cloud directory identities owned by one synchronization run."""

    def __init__(self):
        self.lock = threading.RLock()
        self.directories = {}
        self.child_folders = {}
        self.revision = 0

    def get(self, path):
        with self.lock:
            value = self.directories.get(path)
            if value is None:
                return None
            return dict(value[0]), [dict(item) for group in value[1].values() for item in group]

    def lookup(self, path, name):
        with self.lock:
            value = self.directories.get(path)
            if value is None:
                return None
            return dict(value[0]), [dict(item) for item in value[1].get(name, [])]

    def take_child_folder(self, path):
        parent, name = posixpath.split(path)
        with self.lock:
            return self.child_folders.get(parent, {}).pop(name, None)

    def record(self, path, parent, entries, revision=None, *, path_resolved=True):
        with self.lock:
            # A listing started before a write must not erase that write.
            if revision is None or revision == self.revision:
                by_name = {}
                for item in entries:
                    by_name.setdefault(item['name'], []).append(dict(item))
                self.child_folders[path] = {
                    name: group[0] for name, group in by_name.items()
                    if len(group) == 1 and group[0].get('type') == 'folder' and group[0].get('file_id')
                }
                # An ID observed in a parent listing may still work after an external move.
                # It is a traversal hint, not proof of the destination path for uploads.
                if path_resolved:
                    self.directories[path] = (dict(parent), by_name)
                else:
                    self.directories.pop(path, None)

    def put(self, path, item):
        with self.lock:
            parent_path, name = posixpath.split(path)
            self.child_folders.get(parent_path or '/', {}).pop(name, None)
            value = self.directories.get(parent_path or '/')
            if value is not None:
                value[1][name] = [dict(item, name=name)]
            self.revision += 1

    def invalidate(self, path):
        with self.lock:
            self.take_child_folder(path)
            for cache in (self.directories, self.child_folders):
                for key in list(cache):
                    if key == path or key.startswith(path.rstrip('/') + '/'):
                        del cache[key]
            self.revision += 1
            return self.revision

    def remove(self, path):
        with self.lock:
            parent_path, name = posixpath.split(path)
            value = self.directories.get(parent_path or '/')
            if value is not None:
                value[1].pop(name, None)
            self.invalidate(path)
