"""Publish SHA-256 of the extracted program, not the surrounding archive."""
import hashlib
import sys
import tarfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apiServer.trust_manifest import LABEL, encode_manifest, parse_manifest


def manifest(directory, tag, include_apk=False):
    if not LABEL.fullmatch(tag):
        raise ValueError('invalid build version')
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
        elif include_apk and name == 'android-debug.apk':
            with archive.open('rb') as fp:
                yield hashlib.file_digest(fp, 'sha256').hexdigest(), 'android-arm64-v8a+armeabi-v7a'
        elif include_apk:
            raise ValueError(f'unknown executable artifact: {archive.name}')


if __name__ == '__main__':
    if sys.argv[1] == 'collect':
        _, _, directory, version, output = sys.argv
        rows = [(version, arch, sha) for sha, arch in manifest(Path(directory), version, include_apk=True)]
        if rows:
            Path(output).write_bytes(encode_manifest(rows))
    elif sys.argv[1] == 'merge':
        _, _, previous, addition, output = sys.argv
        old = parse_manifest(Path(previous).read_bytes()) if previous != '-' else []
        Path(output).write_bytes(encode_manifest(old + parse_manifest(Path(addition).read_bytes())))
    else:
        for digest, target in manifest(Path(sys.argv[1]), sys.argv[2]):
            print(digest, target)
