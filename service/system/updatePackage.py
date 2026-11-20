"""Prepare the executable in an uploaded release without installing archive paths."""
import gzip
import hashlib
import os
import stat
import tarfile
import tempfile
import zipfile
import zlib
from pathlib import Path, PureWindowsPath


CHUNK = 128 * 1024
MAX_ENTRIES = 4096
METADATA_BYTES = 2 * 1024 * 1024


class _ReadBudget:
    """Bound expanded tar data and ZIP metadata before the parsers allocate it."""
    def __init__(self, source, limit):
        self.source = source
        self.remaining = limit

    def read(self, size=-1):
        limit = self.remaining + 1
        data = self.source.read(limit if size < 0 else min(size, limit))
        self.remaining -= len(data)
        if self.remaining < 0:
            raise ValueError('update_archive_limit')
        return data

    def __getattr__(self, name):
        return getattr(self.source, name)


def _program_name(name):
    path = PureWindowsPath(name)  # Recognize both separators and drive-qualified names on every host.
    return not path.anchor and '..' not in path.parts and path.name in ('taoSync', 'taoSync.exe')


def _copy_program(source, output, size, limit):
    if not 0 < size <= limit:
        raise ValueError('update_size')
    digest = hashlib.sha256()
    copied = 0
    while chunk := source.read(CHUNK):
        copied += len(chunk)
        if copied > size:
            raise ValueError('update_archive_invalid')
        output.write(chunk)
        digest.update(chunk)
    if copied != size:
        raise ValueError('update_archive_invalid')
    return digest.hexdigest()


def _unzip(source, output, limit):
    reader = _ReadBudget(source, METADATA_BYTES)
    with zipfile.ZipFile(reader) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES:
            raise ValueError('update_archive_limit')
        candidates = [e for e in entries if _program_name(e.orig_filename) and not e.is_dir()
                      and not (e.external_attr & 0x10) and stat.S_IFMT(e.external_attr >> 16) in (0, stat.S_IFREG)]
        if len(candidates) != 1:
            raise ValueError('update_archive_program')
        entry, = candidates
        if entry.flag_bits & 1 or entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError('update_zip_unsupported')
        reader.remaining = limit
        with archive.open(entry) as program:
            return _copy_program(program, output, entry.file_size, limit)


def _untar(source, output, limit):
    digest = None
    with gzip.GzipFile(fileobj=source, mode='rb') as gz:
        reader = _ReadBudget(gz, limit + METADATA_BYTES)
        with tarfile.open(fileobj=reader, mode='r|') as archive:
            for index, entry in enumerate(archive):
                if index >= MAX_ENTRIES:
                    raise ValueError('update_archive_limit')
                if not entry.isfile() or entry.sparse is not None or not _program_name(entry.name):
                    continue
                if digest is not None:
                    raise ValueError('update_archive_program')
                with archive.extractfile(entry) as program:
                    digest = _copy_program(program, output, entry.size, limit)
        # tar stops at its end marker; finish the gzip stream to check its trailer.
        while reader.read(CHUNK):
            pass
    if digest is None:
        raise ValueError('update_archive_program')
    return digest


def prepare_payload(upload, raw_digest, limit):
    """Leave only the candidate executable at upload and return its SHA-256."""
    extracted = None
    try:
        with upload.open('rb') as source:
            magic = source.read(4)
            if magic.startswith(b'\x1f\x8b'):
                unpack = _untar
            elif magic in (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'):
                unpack = _unzip
            else:
                return raw_digest
            source.seek(0)
            with tempfile.NamedTemporaryFile(dir=upload.parent, prefix='payload-', delete=False) as output:
                extracted = Path(output.name)
                digest = unpack(source, output, limit)
                output.flush()
                os.fsync(output.fileno())
        os.replace(extracted, upload)
        return digest
    except (tarfile.TarError, zipfile.BadZipFile, gzip.BadGzipFile, zlib.error, EOFError,
            UnicodeError, RuntimeError) as exc:
        raise ValueError('update_archive_invalid') from exc
    finally:
        if extracted is not None:
            extracted.unlink(missing_ok=True)
