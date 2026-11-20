import asyncio
import os
import platform
import sys
from pathlib import Path

from apiServer.trust_manifest import MAX_MANIFEST_BYTES, SHA256, parse_manifest

from service.system import updateLauncher as launcher

MAX_BYTES = 256 * 1024 * 1024
TRUST_URLS = ('https://taoapi.dr34m.cn/auth.json', 'https://dr34m-cn.github.io/taosync/auth.json')


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
            'supported': enabled, 'maxBytes': MAX_BYTES, 'pinned': bool(os.getenv('TAO_UPDATE_SHA256')),
            'container': Path('/.dockerenv').exists(),
            'result': launcher.read_json(Path(os.environ['TAO_UPDATE_CHANNEL']) / 'result') if enabled else {}}


async def fetch_manifest(url):
    # Source/Android deployments do not use or need the executable update transport.
    import httpx

    try:
        async with asyncio.timeout(20), httpx.AsyncClient(follow_redirects=False) as client:
            async with client.stream('GET', url, headers={'Accept-Encoding': 'identity'}) as res:
                res.raise_for_status()
                raw = bytearray()
                async for chunk in res.aiter_bytes(chunk_size=65536):
                    if len(raw) + len(chunk) > MAX_MANIFEST_BYTES:
                        raise ValueError('manifest too large')
                    raw.extend(chunk)
                return parse_manifest(raw)
    except (httpx.HTTPError, OSError) as exc:
        raise ValueError('manifest unavailable') from exc


async def verify_digest(digest):
    pinned = os.getenv('TAO_UPDATE_SHA256', '').lower()
    if SHA256.fullmatch(pinned) and digest == pinned:
        return
    tasks = [asyncio.create_task(fetch_manifest(url)) for url in TRUST_URLS]
    try:
        for completed in asyncio.as_completed(tasks):
            try:
                rows = await completed
            except ValueError:
                continue
            target = platform_target()
            if any(arch == target and sha == digest for _, arch, sha in rows):
                return
            raise ValueError('update_not_trusted')
        raise ValueError('update_trust_unavailable')
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


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
