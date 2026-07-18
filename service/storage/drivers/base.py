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
    if not name or "/" in str(name) or "\\" in str(name) or str(name) in (".", ".."):
        raise ValueError("invalid file name")
    return normalize_path(posixpath.join(directory, str(name)))


class StorageDriver:
    """Small common contract shared by local, network and cloud drivers."""

    driver_type = "base"

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

    def copy(self, source_path, destination_path, size=None, progress=None, cancel=None):
        """Portable copy fallback used when a backend has no native copy API."""
        stream_transfer(self, source_path, self, destination_path, size, progress, cancel)


def stream_transfer(source_driver, source_path, destination_driver, destination_path,
                    size, progress=None, cancel=None):
    """Stream a cross-backend transfer through a bounded OS pipe."""
    check_cancel(cancel)
    read_fd, write_fd = os.pipe()
    source_errors = []
    internal_cancel = threading.Event()
    transfer_cancel = _CombinedCancel(cancel, internal_cancel)

    def produce():
        try:
            with os.fdopen(write_fd, "wb", buffering=0) as target:
                source_driver.download(
                    source_path,
                    target,
                    _scale_progress(progress, 0.0, 0.5),
                    transfer_cancel,
                )
        except BaseException as exc:
            source_errors.append(exc)
            internal_cancel.set()

    producer = threading.Thread(target=produce, name="taosync-transfer-source", daemon=True)
    producer.start()
    destination_error = None
    try:
        with os.fdopen(read_fd, "rb", buffering=0) as source:
            destination_driver.upload(
                destination_path,
                source,
                size,
                _scale_progress(progress, 0.5, 1.0),
                transfer_cancel,
            )
    except BaseException as exc:
        destination_error = exc
        internal_cancel.set()
    finally:
        # A backend may be blocked in a socket read and therefore cannot be
        # interrupted by an Event alone. Keep the join bounded.
        producer.join(timeout=5)
    producer_stuck = producer.is_alive()
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


def _scale_progress(callback, start, end):
    if callback is None:
        return None

    def report(value):
        callback(start + (end - start) * max(0.0, min(1.0, float(value))))

    return report
