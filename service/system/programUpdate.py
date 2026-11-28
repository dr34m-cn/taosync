import asyncio
import hashlib
import os
import platform
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from apiServer.trust_manifest import (
    DEFAULT_DOWNLOAD_SOURCES,
    MAX_MANIFEST_BYTES,
    artifact_filename,
    parse_latest_details,
    parse_manifest,
    render_download_url,
)

from service.system import updateLauncher as launcher

MAX_BYTES = 256 * 1024 * 1024
TRUST_ORIGINS = ('https://taoapi.dr34m.cn', 'https://dr34m-cn.github.io/taosync')
MANIFEST_TIMEOUT = 20
PROBE_TIMEOUT = 15
DOWNLOAD_CONNECT_TIMEOUT = 20
DOWNLOAD_READ_TIMEOUT = 60
MAX_REDIRECTS = 5
DOWNLOAD_USER_AGENT = 'TaoSync-Updater/1.0'


def current_version():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    fallback = Path(__file__).resolve().parents[2]
    for base in (root, fallback):
        path = base / 'version.txt'
        if path.is_file():
            lines = path.read_text(encoding='utf-8').splitlines()
            if lines:
                value = lines[0].split(',', 1)[0].strip()
                if value:
                    return value
    return ''


def platform_target():
    machine = platform.machine().lower()
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64', 'i686': '386', 'i386': '386',
            'armv7l': 'arm-v7', 'armv6l': 'arm-v6'}.get(machine, machine)
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
    if (root / 'build-target.txt').is_file():
        return (root / 'build-target.txt').read_text().strip().replace('/', '-')
    if os.environ.get('STATICX_PROG_PATH'):
        return 'linux-StaticX-' + ('arm32' if arch.startswith('arm-v') else arch)
    return platform.system().lower() + '-' + arch


def supported():
    return bool(getattr(sys, 'frozen', False) and os.getenv('TAO_UPDATE_CHANNEL') and os.getenv('TAO_UPDATE_DIR'))


def _is_container():
    try:
        return Path('/.dockerenv').exists()
    except OSError:
        return False


def info():
    enabled = supported()
    return {'architecture': platform.machine(), 'target': platform_target(),
            'version': current_version(),
            'supported': enabled, 'maxBytes': MAX_BYTES,
            'container': _is_container(),
            'result': launcher.read_json(Path(os.environ['TAO_UPDATE_CHANNEL']) / 'result') if enabled else {}}


async def _fetch_manifest_bytes_tornado(url):
    import certifi
    from tornado.httpclient import AsyncHTTPClient, HTTPClientError, HTTPRequest

    client = AsyncHTTPClient(force_instance=True, max_body_size=MAX_MANIFEST_BYTES)
    try:
        request = HTTPRequest(
            url, method='GET', headers={'Accept-Encoding': 'identity'},
            follow_redirects=False, connect_timeout=MANIFEST_TIMEOUT, request_timeout=MANIFEST_TIMEOUT,
            ca_certs=certifi.where(),
        )
        async with asyncio.timeout(MANIFEST_TIMEOUT):
            res = await client.fetch(request)
        if len(res.body) > MAX_MANIFEST_BYTES:
            raise ValueError('manifest too large')
        return res.body
    except (HTTPClientError, OSError, TimeoutError) as exc:
        raise ValueError('manifest unavailable') from exc
    finally:
        client.close()


async def fetch_manifest_bytes(url):
    # Source/Android deployments may not bundle httpx; fall back to Tornado's async client.
    try:
        import httpx
    except ImportError:
        return await _fetch_manifest_bytes_tornado(url)

    try:
        timeout = httpx.Timeout(
            connect=MANIFEST_TIMEOUT,
            read=MANIFEST_TIMEOUT,
            write=MANIFEST_TIMEOUT,
            pool=MANIFEST_TIMEOUT,
        )
        async with asyncio.timeout(MANIFEST_TIMEOUT), httpx.AsyncClient(
            follow_redirects=False, timeout=timeout
        ) as client:
            async with client.stream('GET', url, headers={'Accept-Encoding': 'identity'}) as res:
                res.raise_for_status()
                raw = bytearray()
                async for chunk in res.aiter_bytes(chunk_size=65536):
                    if len(raw) + len(chunk) > MAX_MANIFEST_BYTES:
                        raise ValueError('manifest too large')
                    raw.extend(chunk)
                return bytes(raw)
    except (httpx.HTTPError, OSError, TimeoutError) as exc:
        raise ValueError('manifest unavailable') from exc


async def fetch_manifest(url):
    return parse_manifest(await fetch_manifest_bytes(url))


async def fetch_latest_manifest_details(url):
    return parse_latest_details(await fetch_manifest_bytes(url))


async def fetch_latest_manifest(url):
    version, rows, _downloads = await fetch_latest_manifest_details(url)
    return version, rows


async def fetch_first_latest_details():
    """Race latest.json across both trust origins; return the first valid response and close the other."""
    async def fetch_one(origin):
        url = f"{origin.rstrip('/')}/latest.json"
        version, rows, downloads = await fetch_latest_manifest_details(url)
        return origin, version, rows, downloads

    tasks = [asyncio.create_task(fetch_one(origin)) for origin in TRUST_ORIGINS]
    try:
        for completed in asyncio.as_completed(tasks):
            try:
                return await completed
            except ValueError:
                continue
        raise ValueError('update_trust_unavailable')
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def fetch_first_latest():
    origin, version, rows, _downloads = await fetch_first_latest_details()
    return origin, version, rows


def _resolve_version_sources(item, filename, target):
    resolved = []
    for source in item.get('sources', []):
        url = render_download_url(
            source['urlTemplate'],
            version=item['version'],
            filename=filename,
            arch=target,
        )
        entry = {'id': source['id'], 'name': source['name'], 'url': url}
        if 'labels' in source:
            entry['labels'] = dict(source['labels'])
        resolved.append(entry)
    return resolved


def build_online_releases(latest_version, latest_rows, downloads, *, target=None, current=None):
    target = platform_target() if target is None else target
    current = current_version() if current is None else current
    versions = []
    if downloads and downloads.get('versions'):
        for item in downloads['versions']:
            filename = item.get('assets', {}).get(target)
            if not filename:
                continue
            versions.append({
                'version': item['version'],
                'channel': item['channel'],
                'isLatestStable': bool(
                    latest_version and item['version'] == latest_version and item['channel'] == 'stable'
                ),
                'publishedAt': item.get('publishedAt'),
                'filename': filename,
                'sources': _resolve_version_sources(item, filename, target),
            })
    elif latest_version and any(arch == target for _ver, arch, _sha in latest_rows):
        filename = artifact_filename(latest_version, target)
        if filename:
            fallback_item = {
                'version': latest_version,
                'channel': 'stable',
                'sources': DEFAULT_DOWNLOAD_SOURCES['stable'],
            }
            versions.append({
                'version': latest_version,
                'channel': 'stable',
                'isLatestStable': True,
                'publishedAt': None,
                'filename': filename,
                'sources': _resolve_version_sources(fallback_item, filename, target),
            })
    latest_available = any(item['isLatestStable'] for item in versions)
    return {
        'currentVersion': current,
        'latestVersion': latest_version,
        'latestAvailable': latest_available,
        'target': target,
        'versions': versions,
    }


async def get_online_releases():
    _origin, latest_version, latest_rows, downloads = await fetch_first_latest_details()
    return build_online_releases(latest_version, latest_rows, downloads)


def resolve_online_selection(catalog, version_choice='latest', source_choice='auto'):
    version_key = (version_choice or 'latest').strip() if isinstance(version_choice, str) else 'latest'
    source_key = (source_choice or 'auto').strip() if isinstance(source_choice, str) else 'auto'
    versions = catalog.get('versions') or []
    if version_key == 'latest':
        selected = next((item for item in versions if item.get('isLatestStable')), None)
    else:
        selected = next((item for item in versions if item.get('version') == version_key), None)
    if selected is None:
        raise ValueError('update_version_unavailable')
    current = (catalog.get('currentVersion') or '').strip()
    if current and selected.get('version') == current:
        raise ValueError('update_already_running')
    sources = selected.get('sources') or []
    if not sources:
        raise ValueError('update_source_unavailable')
    if source_key == 'auto':
        return selected, list(sources), True
    matched = next((src for src in sources if src.get('id') == source_key), None)
    if matched is None:
        raise ValueError('update_source_unavailable')
    return selected, [matched], False


def _validate_https_target(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('update_download_failed')
    return url


@asynccontextmanager
async def _open_https_stream(client, method, url, *, headers=None):
    current = _validate_https_target(url)
    req_headers = {'User-Agent': DOWNLOAD_USER_AGENT, 'Accept-Encoding': 'identity'}
    if headers:
        req_headers.update(headers)
    for hop in range(MAX_REDIRECTS + 1):
        stream_cm = client.stream(method, current, headers=req_headers)
        res = await stream_cm.__aenter__()
        if res.status_code in (301, 302, 303, 307, 308):
            location = res.headers.get('location')
            await stream_cm.__aexit__(None, None, None)
            if not location or hop >= MAX_REDIRECTS:
                raise ValueError('update_download_failed')
            current = _validate_https_target(urljoin(current, location))
            continue
        try:
            yield res
        finally:
            await stream_cm.__aexit__(None, None, None)
        return
    raise ValueError('update_download_failed')


def _declared_size(res):
    if res.status_code == 206:
        content_range = res.headers.get('content-range', '')
        if '/' in content_range:
            total = content_range.rsplit('/', 1)[-1].strip()
            if total.isdigit():
                return int(total)
        return None
    length = (res.headers.get('content-length') or '').strip()
    return int(length) if length.isdigit() else None


async def probe_source(source, *, timeout=PROBE_TIMEOUT):
    import httpx

    start = time.monotonic()
    try:
        async with asyncio.timeout(timeout), httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(connect=timeout, read=timeout, write=timeout, pool=timeout),
        ) as client:
            async with _open_https_stream(
                client, 'GET', source['url'], headers={'Range': 'bytes=0-0'}
            ) as res:
                if res.status_code not in (200, 206):
                    raise ValueError('update_source_unreachable')
                content_type = (res.headers.get('content-type') or '').lower()
                if 'text/html' in content_type:
                    raise ValueError('update_source_unreachable')
                total = _declared_size(res)
                if total is not None and not 0 < total <= MAX_BYTES:
                    raise ValueError('update_size')
                got_bytes = False
                async for chunk in res.aiter_bytes(chunk_size=1):
                    if chunk:
                        got_bytes = True
                        break
                if not got_bytes:
                    raise ValueError('update_source_unreachable')
                return source, max(1, int((time.monotonic() - start) * 1000))
    except (httpx.HTTPError, OSError, TimeoutError, ValueError) as exc:
        raise ValueError('update_source_unreachable') from exc


async def select_fastest_source(sources):
    if not sources:
        raise ValueError('update_source_unavailable')
    if len(sources) == 1:
        return sources[0], None
    tasks = [asyncio.create_task(probe_source(source)) for source in sources]
    try:
        for completed in asyncio.as_completed(tasks):
            try:
                return await completed
            except ValueError:
                continue
        raise ValueError('update_source_unreachable')
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def download_package(url, destination, *, limit=MAX_BYTES, on_progress=None):
    import httpx

    digest = hashlib.sha256()
    downloaded = 0
    total = None
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(
                connect=DOWNLOAD_CONNECT_TIMEOUT,
                read=DOWNLOAD_READ_TIMEOUT,
                write=30,
                pool=20,
            ),
        ) as client:
            async with _open_https_stream(client, 'GET', url) as res:
                if res.status_code != 200:
                    raise ValueError('update_download_failed')
                content_type = (res.headers.get('content-type') or '').lower()
                if 'text/html' in content_type:
                    raise ValueError('update_download_failed')
                total = _declared_size(res)
                if total is not None and not 0 < total <= limit:
                    raise ValueError('update_size')
                if on_progress is not None:
                    on_progress(0, total)
                with Path(destination).open('wb') as output:
                    async for chunk in res.aiter_bytes(chunk_size=65536):
                        if not chunk:
                            continue
                        downloaded += len(chunk)
                        if downloaded > limit:
                            raise ValueError('update_size')
                        output.write(chunk)
                        digest.update(chunk)
                        if on_progress is not None:
                            on_progress(downloaded, total)
                    output.flush()
                    os.fsync(output.fileno())
    except ValueError:
        raise
    except (httpx.HTTPError, TimeoutError) as exc:
        raise ValueError('update_download_failed') from exc
    if downloaded <= 0:
        raise ValueError('update_size')
    if total is not None and downloaded != total:
        raise ValueError('update_download_failed')
    return digest.hexdigest()


class ArchitectureMismatch(ValueError):
    def __init__(self, target, packages):
        super().__init__('update_wrong_arch')
        self.details = {'system': target, 'package': ', '.join(sorted(packages))}


async def verify_digest(digest, expected_version=None):
    target = platform_target()
    origin, _version, latest_rows = await fetch_first_latest()
    packages = set()
    other_versions = set()

    def collect(rows):
        for ver, arch, sha in rows:
            if sha != digest:
                continue
            if expected_version is None or ver == expected_version:
                packages.add(arch)
            else:
                other_versions.add(ver)

    collect(latest_rows)
    if target in packages:
        return
    incomplete = False
    for name in ('auth.json', 'auth-dev.json'):
        try:
            rows = await fetch_manifest(f"{origin.rstrip('/')}/{name}")
        except ValueError:
            incomplete = True
            continue
        collect(rows)
        if target in packages:
            return
    if packages:
        raise ArchitectureMismatch(target, packages)
    if other_versions:
        raise ValueError('update_version_mismatch')
    if incomplete:
        raise ValueError('update_trust_unavailable')
    raise ValueError('update_not_trusted')


async def check_latest_version():
    current = current_version()
    try:
        _origin, latest, _rows = await fetch_first_latest()
    except ValueError:
        return {
            'currentVersion': current,
            'latestVersion': None,
            'hasUpdate': False,
            'checked': False,
        }
    return {
        'currentVersion': current,
        'latestVersion': latest,
        'hasUpdate': bool(latest and current and latest != current),
        'checked': True,
    }


def install_verified(upload, digest, request_id):
    dest = launcher.slot(upload.parent, digest)
    if dest == launcher.executable():
        raise ValueError('update_already_running')
    upload.chmod(0o700)
    os.replace(upload, dest)
    try:
        launcher.write_json(Path(os.environ['TAO_UPDATE_CHANNEL']) / 'request', {'id': request_id, 'digest': digest})
    except OSError:
        dest.unlink(missing_ok=True)
        raise
