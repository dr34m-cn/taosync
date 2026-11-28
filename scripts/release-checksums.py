"""Publish SHA-256 of the extracted program, not the surrounding archive."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apiServer.trust_manifest import (
    DEV_DOWNLOAD_RETENTION,
    LABEL,
    LEGACY_STABLE_FALLBACK_SOURCES,
    STABLE_DOWNLOAD_RETENTION,
    build_downloads_catalog,
    encode_manifest,
    group_channel_builds,
    load_download_sources,
    normalize_version_sources,
    parse_builds,
    parse_version_sources,
    render_download_url,
    split_builds,
)

PROBE_TIMEOUT = 15
PROBE_MAX_REDIRECTS = 5
PROBE_USER_AGENT = 'TaoSync-ReleaseProbe/1.0'
STABLE_PROBE_LIMIT = max(STABLE_DOWNLOAD_RETENTION * 2, 6)
DEV_PROBE_LIMIT = max(DEV_DOWNLOAD_RETENTION * 3, 6)


class _HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    max_redirections = PROBE_MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        if urlsplit(target).scheme.lower() != 'https':
            raise urllib.error.URLError('refused non-HTTPS redirect')
        return super().redirect_request(req, fp, code, msg, headers, target)


def probe_download_url(url, timeout=PROBE_TIMEOUT):
    """Probe whether an artifact actually exists at `url`.

    Returns:
      True  - confirmed present (HTTP 200/206, non-HTML, >=1 byte)
      False - confirmed absent (HTTP 403/404/410, HTML error page, or empty)
      None  - transient failure (timeout / network error / 5xx / 429)
    """
    if urlsplit(url).scheme.lower() != 'https':
        return False
    opener = urllib.request.build_opener(_HttpsOnlyRedirectHandler())
    request = urllib.request.Request(
        url,
        method='GET',
        headers={
            'Range': 'bytes=0-0',
            'Accept-Encoding': 'identity',
            'Cache-Control': 'no-cache',
            'User-Agent': PROBE_USER_AGENT,
        },
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            status = getattr(response, 'status', response.getcode())
            if status not in (200, 206):
                return False
            content_type = (response.headers.get('Content-Type') or '').lower()
            if 'text/html' in content_type:
                return False
            chunk = response.read(1)
            return bool(chunk)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404, 410):
            return False
        return None
    except (urllib.error.URLError, OSError, TimeoutError):
        return None


def load_publish_receipts(receipt_dir):
    if not receipt_dir:
        return []
    path = Path(receipt_dir)
    if not path.is_dir():
        return []
    receipts = []
    for item in sorted(path.glob('*.json')):
        data = json.loads(item.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            continue
        source_id = data.get('source')
        version = data.get('version')
        if (
            not isinstance(source_id, str)
            or not LABEL.fullmatch(source_id)
            or source_id.lower() == 'auto'
            or not isinstance(version, str)
            or not LABEL.fullmatch(version)
        ):
            continue
        entry = {'source': source_id, 'version': version}
        present = data.get('presentVersions')
        if isinstance(present, list):
            entry['presentVersions'] = [
                ver for ver in present if isinstance(ver, str) and LABEL.fullmatch(ver)
            ]
        receipts.append(entry)
    return receipts


def _pick_probe_asset(assets):
    if not assets:
        return None, None
    if 'linux-amd64' in assets:
        return 'linux-amd64', assets['linux-amd64']
    arch = sorted(assets)[0]
    return arch, assets[arch]


def resolve_version_sources(
    stable,
    dev,
    download_sources,
    *,
    prior_version_sources=None,
    receipts=None,
    probe=False,
    probe_fn=None,
):
    """Resolve per-version available source IDs from prior state, CI receipts, and live HTTPS probes."""
    stable_order, stable_grouped = group_channel_builds(stable, 'stable')
    dev_order, dev_grouped = group_channel_builds(dev, 'dev')
    all_versions = set(stable_grouped) | set(dev_grouped)

    prior = {}
    if prior_version_sources:
        for ver, src_ids in normalize_version_sources(prior_version_sources).items():
            if ver in all_versions:
                prior[ver] = set(src_ids)

    receipt_list = list(receipts or [])
    if not probe and not receipt_list and not prior:
        return None

    resolved = {ver: set(ids) for ver, ids in prior.items()}
    authoritative = {}

    for receipt in receipt_list:
        src_id = receipt['source']
        ver = receipt['version']
        if 'presentVersions' in receipt:
            present = set(receipt['presentVersions']) | {ver}
            for known in all_versions:
                is_present = known in present
                authoritative[(known, src_id)] = is_present
                resolved.setdefault(known, set())
                if is_present:
                    resolved[known].add(src_id)
                else:
                    resolved[known].discard(src_id)
        elif ver in all_versions:
            authoritative[(ver, src_id)] = True
            resolved.setdefault(ver, set()).add(src_id)

    if probe:
        prober = probe_download_url if probe_fn is None else probe_fn
        tasks = []
        channel_specs = (
            ('stable', stable_order[:STABLE_PROBE_LIMIT], stable_grouped),
            ('dev', dev_order[:DEV_PROBE_LIMIT], dev_grouped),
        )
        for channel, candidates, grouped in channel_specs:
            channel_sources = download_sources.get(channel, [])
            for ver in candidates:
                arch, filename = _pick_probe_asset(grouped[ver]['assets'])
                if not filename:
                    continue
                for source in channel_sources:
                    src_id = source['id']
                    if (ver, src_id) in authoritative:
                        continue
                    url = render_download_url(
                        source['urlTemplate'],
                        version=ver,
                        filename=filename,
                        arch=arch,
                    )
                    tasks.append((ver, src_id, url))

        if tasks:
            with ThreadPoolExecutor(max_workers=min(8, len(tasks))) as pool:
                futures = [(ver, src_id, pool.submit(prober, url)) for ver, src_id, url in tasks]
                for ver, src_id, future in futures:
                    exists = future.result()
                    if exists is True:
                        resolved.setdefault(ver, set()).add(src_id)
                    elif exists is False:
                        resolved.setdefault(ver, set()).discard(src_id)
                    else:
                        # Transient network error: preserve prior verified state (or legacy github
                        # for unrecorded stable releases), never invent R2/custom sources.
                        if ver in prior:
                            resolved.setdefault(ver, set())
                            if src_id in prior[ver]:
                                resolved[ver].add(src_id)
                            else:
                                resolved[ver].discard(src_id)
                        elif ver in stable_grouped and src_id in LEGACY_STABLE_FALLBACK_SOURCES:
                            resolved.setdefault(ver, set()).add(src_id)

    return normalize_version_sources({ver: sorted(ids) for ver, ids in resolved.items()})


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


def _parse_split_args(raw_args):
    args = list(raw_args)
    sources_path = None
    receipts_dir = None
    probe = False
    i = 0
    positional = []
    while i < len(args):
        if args[i] == '--sources' and i + 1 < len(args):
            sources_path = args[i + 1]
            i += 2
        elif args[i] == '--receipts' and i + 1 < len(args):
            receipts_dir = args[i + 1]
            i += 2
        elif args[i] == '--probe':
            probe = True
            i += 1
        else:
            positional.append(args[i])
            i += 1
    return sources_path, receipts_dir, probe, positional


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
        sources_path, receipts_dir, probe, positional = _parse_split_args(sys.argv[2:])
        stable_out, dev_out, latest_out, *sources = positional
        combined = []
        prior_version_sources = {}
        for source in sources:
            if source != '-':
                raw = Path(source).read_bytes()
                combined.extend(parse_builds(raw))
                parsed_vs = parse_version_sources(raw)
                if parsed_vs is not None:
                    for ver, src_ids in parsed_vs.items():
                        prior_version_sources.setdefault(ver, set()).update(src_ids)
        stable, dev, latest_version, latest = split_builds(combined)
        download_sources = load_download_sources(sources_path)
        receipts = load_publish_receipts(receipts_dir)
        version_sources = resolve_version_sources(
            stable,
            dev,
            download_sources,
            prior_version_sources={ver: sorted(ids) for ver, ids in prior_version_sources.items()} or None,
            receipts=receipts,
            probe=probe,
        )
        downloads = build_downloads_catalog(stable, dev, download_sources, version_sources=version_sources)
        Path(stable_out).write_bytes(
            encode_manifest(stable, download_sources=download_sources, version_sources=version_sources)
        )
        Path(dev_out).write_bytes(
            encode_manifest(dev, download_sources=download_sources, version_sources=version_sources)
        )
        Path(latest_out).write_bytes(encode_manifest(latest, version=latest_version, downloads=downloads))
    else:
        for digest, target in manifest(Path(sys.argv[1]), sys.argv[2]):
            print(digest, target)
