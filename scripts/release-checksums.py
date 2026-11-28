"""Publish SHA-256 of the extracted program, not the surrounding archive."""
import hashlib
import sys
import tarfile
import zipfile
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apiServer.trust_manifest import (
    LABEL,
    build_downloads_catalog,
    encode_manifest,
    load_download_sources,
    parse_builds,
    split_builds,
)


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
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        rows = [(version, arch, sha, stamp) for sha, arch in manifest(Path(directory), version, include_apk=True)]
        if rows:
            Path(output).write_bytes(encode_manifest(rows))
    elif sys.argv[1] == 'merge':
        _, _, previous, addition, output = sys.argv
        old = parse_builds(Path(previous).read_bytes()) if previous != '-' else []
        Path(output).write_bytes(encode_manifest(old + parse_builds(Path(addition).read_bytes())))
    elif sys.argv[1] == 'split':
        args = sys.argv[2:]
        sources_path = None
        if len(args) >= 2 and args[0] == '--sources':
            sources_path = args[1]
            args = args[2:]
        stable_out, dev_out, latest_out, *sources = args
        combined = []
        for source in sources:
            if source != '-':
                combined.extend(parse_builds(Path(source).read_bytes()))
        stable, dev, latest_version, latest = split_builds(combined)
        download_sources = load_download_sources(sources_path)
        downloads = build_downloads_catalog(stable, dev, download_sources)
        Path(stable_out).write_bytes(encode_manifest(stable, download_sources=download_sources))
        Path(dev_out).write_bytes(encode_manifest(dev, download_sources=download_sources))
        Path(latest_out).write_bytes(encode_manifest(latest, version=latest_version, downloads=downloads))
    else:
        for digest, target in manifest(Path(sys.argv[1]), sys.argv[2]):
            print(digest, target)
