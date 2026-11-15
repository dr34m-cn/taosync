import os
import posixpath
import threading


class TransferCancelled(Exception):
    """Raised by a driver when an in-flight transfer is cancelled."""


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise TransferCancelled("transfer cancelled")


class _CombinedCancel:
    def __init__(self, external, internal):
        self.external = external
        self.internal = internal

    def is_set(self):
        return self.internal.is_set() or (self.external is not None and self.external.is_set())


def normalize_path(path, allow_root=True):
    """Normalize a virtual or driver-relative POSIX path safely."""
    if path is None:
        raise ValueError("path is required")
    path = str(path).replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path
    parts = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path traversal is not allowed")
        parts.append(part)
    result = "/" + "/".join(parts)
    if result == "/" and not allow_root:
        raise ValueError("root path is not allowed")
    return result


def child_path(directory, name):
    directory = normalize_path(directory)
    if (not name or "/" in str(name) or "\\" in str(name) or str(name) in (".", "..")
            or any(ord(char) < 32 for char in str(name))):
        raise ValueError("invalid file name")
    return normalize_path(posixpath.join(directory, str(name)))


class StorageDriver:
    """Small common contract shared by local, network and cloud drivers."""

    driver_type = "base"
    supports_random_read = False

    def list(self, path, details=False):
        raise NotImplementedError

    def mkdir(self, path):
        raise NotImplementedError

    def delete(self, path):
        raise NotImplementedError

    def download(self, path, target, progress=None, cancel=None):
        raise NotImplementedError

    def upload(self, path, source, size=None, progress=None, cancel=None):
        raise NotImplementedError

    def file_metadata(self, path):
        parent, name = posixpath.split(normalize_path(path, allow_root=False))
        for entry in self.list(parent or "/", details=True):
            if entry["name"] == name and not entry["is_dir"]:
                return dict(entry)
        raise FileNotFoundError(path)

    def move(self, source_path, destination_path, size=None, progress=None, cancel=None):
        raise NotImplementedError

    def rename(self, path, name, cancel=None):
        raise NotImplementedError

    def copy(self, source_path, destination_path, size=None, progress=None, cancel=None):
        """Portable copy fallback used when a backend has no native copy API."""
        stream_transfer(self, source_path, self, destination_path, size, progress, cancel)


class _SourceReader:
    def __init__(self, driver, path, cancel, errors, metadata):
        self.driver, self.path, self.cancel = driver, path, cancel
        self.errors = errors
        self.metadata = dict(metadata or {})
        self.can_read_range = isinstance(driver, StorageDriver) and driver.supports_random_read is True
        self.pipe = None
        self.producer = None

    def read_range(self, offset, length):
        check_cancel(self.cancel)
        return self.driver.read_range(self.path, offset, length, cancel=self.cancel)

    def read(self, size=-1):
        check_cancel(self.cancel)
        if self.pipe is None:
            read_fd, write_fd = os.pipe()
            self.pipe = os.fdopen(read_fd, "rb", buffering=0)

            def produce():
                try:
                    with os.fdopen(write_fd, "wb", buffering=0) as target:
                        self.driver.download(self.path, target, None, self.cancel)
                except BaseException as exc:
                    self.errors.append(exc)
                    self.cancel.internal.set()

            self.producer = threading.Thread(target=produce, name="taosync-transfer-source", daemon=True)
            self.producer.start()
        return self.pipe.read(size)

    def close(self):
        if self.pipe is not None:
            self.pipe.close()


def stream_transfer(source_driver, source_path, destination_driver, destination_path,
                    size, progress=None, cancel=None, metadata=None):
    """Stream a cross-backend transfer through a bounded OS pipe."""
    check_cancel(cancel)
    source_errors = []
    internal_cancel = threading.Event()
    transfer_cancel = _CombinedCancel(cancel, internal_cancel)

    if metadata is None and isinstance(source_driver, StorageDriver):
        metadata = source_driver.file_metadata(source_path)
    source = _SourceReader(source_driver, source_path, transfer_cancel, source_errors, metadata)
    destination_error = None
    try:
        destination_driver.upload(destination_path, source, size, progress, transfer_cancel)
    except BaseException as exc:
        destination_error = exc
        internal_cancel.set()
    finally:
        source.close()
        # A backend may be blocked in a socket read and therefore cannot be
        # interrupted by an Event alone. Keep the join bounded.
        if source.producer is not None:
            source.producer.join(timeout=5)
    producer = source.producer
    producer_stuck = producer is not None and producer.is_alive()
    if producer_stuck:
        internal_cancel.set()
        producer.join(timeout=1)
        producer_stuck = producer.is_alive()
        if producer_stuck and destination_error is None:
            if cancel is not None and cancel.is_set():
                raise TransferCancelled("transfer cancelled")
            raise IOError("source transfer did not terminate after destination completed")
    source_error = source_errors[0] if source_errors else None
    # Once the destination driver has returned, its atomic commit is complete.
    # A source-side cancellation observed while it is only closing the pipe
    # must not relabel that committed destination as a failed transfer.
    if destination_error is None and (
        source_error is None or isinstance(source_error, TransferCancelled)
    ):
        if metadata is not None:
            metadata.update(source.metadata)
        return
    # An external cancellation must win over a destination-side EOF/length
    # error, but a normal destination failure must not be masked by the
    # source observing the internal stop event and raising TransferCancelled.
    external_cancelled = cancel is not None and cancel.is_set()
    if external_cancelled:
        raise TransferCancelled("transfer cancelled")
    if destination_error is not None:
        # If the source failed first, the destination can observe the
        # internal stop event as TransferCancelled. Preserve the source's
        # real error in that case.
        if isinstance(destination_error, TransferCancelled) and source_error is not None \
                and not isinstance(source_error, TransferCancelled):
            raise source_error
        if isinstance(destination_error, TransferCancelled):
            raise TransferCancelled("transfer cancelled")
        raise destination_error
    if source_error is not None:
        if isinstance(source_error, TransferCancelled):
            raise TransferCancelled("transfer cancelled")
        raise source_error
