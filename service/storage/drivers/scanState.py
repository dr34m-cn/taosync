import posixpath
import threading


class ScanState:
    """Raw cloud directory identities owned by one synchronization run."""

    def __init__(self):
        self.lock = threading.RLock()
        self.directories = {}
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

    def record(self, path, parent, entries, revision=None):
        with self.lock:
            # A listing started before a write must not erase that write.
            if revision is None or revision == self.revision:
                by_name = {}
                for item in entries:
                    by_name.setdefault(item['name'], []).append(dict(item))
                self.directories[path] = (dict(parent), by_name)

    def put(self, path, item):
        with self.lock:
            parent_path, name = posixpath.split(path)
            value = self.directories.get(parent_path or '/')
            if value is not None:
                value[1][name] = [dict(item, name=name)]
            self.revision += 1

    def invalidate(self, path):
        with self.lock:
            for key in list(self.directories):
                if key == path or key.startswith(path.rstrip('/') + '/'):
                    del self.directories[key]
            self.revision += 1

    def remove(self, path):
        with self.lock:
            parent_path, name = posixpath.split(path)
            value = self.directories.get(parent_path or '/')
            if value is not None:
                value[1].pop(name, None)
            self.invalidate(path)
