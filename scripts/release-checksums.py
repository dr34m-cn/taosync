"""Publish SHA-256 of the extracted program, not the surrounding archive."""
import hashlib
import sys
import tarfile
import zipfile
from pathlib import Path


def manifest(directory, tag):
    prefix = f'taoSync-{tag}-'
    for archive in sorted(directory.glob(prefix + '*')):
        name = archive.name[len(prefix):]
        if name.endswith('.zip'):
            with zipfile.ZipFile(archive) as package:
                with package.open('taoSync.exe' if name.startswith('windows-') else 'taoSync') as fp:
                    yield hashlib.file_digest(fp, 'sha256').hexdigest(), name[:-4]
        elif name.endswith('.tar.gz'):
            with tarfile.open(archive, 'r:gz') as package:
                entry, = [m for m in package if m.isfile() and m.name in ('taoSync', './taoSync')]
                with package.extractfile(entry) as fp:
                    yield hashlib.file_digest(fp, 'sha256').hexdigest(), name[:-7]


if __name__ == '__main__':
    for digest, target in manifest(Path(sys.argv[1]), sys.argv[2]):
        print(digest, target)
