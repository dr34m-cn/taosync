import asyncio
import os
import platform
import sys
from pathlib import Path

from apiServer.trust_manifest import MAX_MANIFEST_BYTES, parse_latest, parse_manifest

from service.system import updateLauncher as launcher

MAX_BYTES = 256 * 1024 * 1024
TRUST_ORIGINS = ('https://taoapi.dr34m.cn', 'https://dr34m-cn.github.io/taosync')


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


def info():
    enabled = supported()
    return {'architecture': platform.machine(), 'target': platform_target(),
            'version': current_version(),
            'supported': enabled, 'maxBytes': MAX_BYTES,
            'container': Path('/.dockerenv').exists(),
            'result': launcher.read_json(Path(os.environ['TAO_UPDATE_CHANNEL']) / 'result') if enabled else {}}


async def _fetch_manifest_bytes_tornado(url):
    import certifi
    from tornado.httpclient import AsyncHTTPClient, HTTPClientError, HTTPRequest

    client = AsyncHTTPClient(force_instance=True, max_body_size=MAX_MANIFEST_BYTES)
    try:
        request = HTTPRequest(
            url, method='GET', headers={'Accept-Encoding': 'identity'},
            follow_redirects=False, connect_timeout=20, request_timeout=20,
            ca_certs=certifi.where(),
        )
        async with asyncio.timeout(20):
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
        async with asyncio.timeout(20), httpx.AsyncClient(follow_redirects=False) as client:
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


async def fetch_latest_manifest(url):
    return parse_latest(await fetch_manifest_bytes(url))


async def fetch_first_latest():
    """Race latest.json across both trust origins; return the first valid response and close the other."""
    async def fetch_one(origin):
        url = f"{origin.rstrip('/')}/latest.json"
        version, rows = await fetch_latest_manifest(url)
        return origin, version, rows

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


class ArchitectureMismatch(ValueError):
    def __init__(self, target, packages):
        super().__init__('update_wrong_arch')
        self.details = {'system': target, 'package': ', '.join(sorted(packages))}


async def verify_digest(digest):
    target = platform_target()
    origin, _version, latest_rows = await fetch_first_latest()
    packages = {arch for _, arch, sha in latest_rows if sha == digest}
    if target in packages:
        return
    incomplete = False
    for name in ('auth.json', 'auth-dev.json'):
        try:
            rows = await fetch_manifest(f"{origin.rstrip('/')}/{name}")
        except ValueError:
            incomplete = True
            continue
        packages.update(arch for _, arch, sha in rows if sha == digest)
        if target in packages:
            return
    if packages:
        raise ArchitectureMismatch(target, packages)
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
