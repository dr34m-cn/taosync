import os
import platform
import re
import sys
from pathlib import Path

import requests

from service.system import updateLauncher as launcher

MAX_BYTES = 256 * 1024 * 1024
RELEASES = 'https://github.com/dr34m-cn/taosync/releases'


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
    return {'architecture': platform.machine() or '未知', 'target': platform_target(),
            'supported': enabled, 'maxBytes': MAX_BYTES, 'pinned': bool(os.getenv('TAO_UPDATE_SHA256')),
            'container': Path('/.dockerenv').exists(),
            'result': launcher.read_json(Path(os.environ['TAO_UPDATE_CHANNEL']) / 'result') if enabled else {}}


def trusted_digest():
    pinned = os.getenv('TAO_UPDATE_SHA256')
    if pinned:
        if not re.fullmatch('[a-fA-F0-9]{64}', pinned):
            raise ValueError('部署时配置的 TAO_UPDATE_SHA256 无效')
        return pinned.lower()
    try:
        with requests.get(f'{RELEASES}/latest/download/taoSync-checksums.txt', timeout=(5, 15), stream=True) as res:
            res.raise_for_status()
            # The upload never supplies a URL or a trusted digest.
            manifest = res.raw.read(16385, decode_content=True)
            if len(manifest) > 16384:
                raise ValueError('发布校验清单过大')
    except (requests.RequestException, OSError) as exc:
        raise ValueError('无法获取最新正式版的校验清单，请检查网络；离线部署可预设 TAO_UPDATE_SHA256') from exc
    for line in manifest.decode('ascii').splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == platform_target() and re.fullmatch('[0-9a-f]{64}', fields[0]):
            return fields[0]
    raise ValueError('该版本没有适用于当前平台的可执行文件')


def install_verified(upload, digest, expected, request_id):
    if digest != expected:
        raise ValueError('校验未通过，请选择对应平台发布包内解压出的 TaoSync 可执行文件')
    dest = launcher.slot(upload.parent, digest)
    if dest == launcher.executable():
        raise ValueError('当前已在运行这个程序')
    upload.chmod(0o700)
    os.replace(upload, dest)
    try:
        launcher.write_json(Path(os.environ['TAO_UPDATE_CHANNEL']) / 'request', {'id': request_id, 'digest': digest})
    except OSError:
        dest.unlink(missing_ok=True)
        raise
