"""Stable parent for one-file builds. The executable started by Docker/the OS stays put."""
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RESTART = 75
WORKER = '--taosync-worker'
START_TIMEOUT = 120


def executable():
    # StaticX extracts the inner PyInstaller executable to a temporary directory.
    return Path(os.environ.get('STATICX_PROG_PATH') or sys.executable).resolve()


def slot(directory, digest):
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('无效的更新摘要')
    return directory / (digest + ('.exe' if os.name == 'nt' else '.bin'))


def file_digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_json(path, data):
    fd, filename = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fp:
            json.dump(data, fp)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(filename, path)
    finally:
        Path(filename).unlink(missing_ok=True)


def read_json(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def child_env(directory, channel):
    env = os.environ.copy()
    env.update(TAO_UPDATE_DIR=str(directory), TAO_UPDATE_CHANNEL=str(channel),
               PYINSTALLER_RESET_ENVIRONMENT='1')
    for key in ('STATICX_BUNDLE_DIR', 'STATICX_PROG_PATH'):
        env.pop(key, None)
    if 'LD_LIBRARY_PATH_ORIG' in env:
        env['LD_LIBRARY_PATH'] = env.pop('LD_LIBRARY_PATH_ORIG')
    else:
        env.pop('LD_LIBRARY_PATH', None)
    return env


def stop_tree(child):
    if child.poll() is not None:
        return
    if os.name == 'nt':
        # One-file bootloaders have a second process holding the HTTP socket.
        taskkill = Path(os.environ['SystemRoot']) / 'System32' / 'taskkill.exe'
        subprocess.run([str(taskkill), '/PID', str(child.pid), '/T', '/F'], check=False)
    else:
        try:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    child.wait()


def supervise(base, args):
    directory = base.parent / ('.' + base.name + '-updates')
    state_file = directory / 'active.json'
    stamp = [base.stat().st_size, base.stat().st_mtime_ns]
    state = read_json(state_file)
    active = state.get('active') if state.get('base') == stamp else None
    candidate = active
    attempt = None
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, stop)

    with tempfile.TemporaryDirectory(prefix='taosync-launch-') as tmp:
        channel = Path(tmp)
        env = child_env(directory, channel)
        if state.get('base') == stamp and state.get('result'):
            write_json(channel / 'result', state['result'])
        while not stopping:
            child = None
            ready = channel / 'ready'
            ready.unlink(missing_ok=True)
            try:
                target = slot(directory, candidate) if candidate else base
                if candidate and file_digest(target) != candidate:
                    raise ValueError('更新文件校验失败')
                child = subprocess.Popen([str(target), WORKER, *args], env=env,
                                         start_new_session=os.name != 'nt')
                if candidate:
                    deadline = time.monotonic() + START_TIMEOUT
                    while not ready.exists():
                        if stopping:
                            return 0
                        if child.poll() is not None or time.monotonic() >= deadline:
                            raise RuntimeError('更新程序未能启动服务')
                        time.sleep(.2)
                    if child.poll() is not None:
                        raise RuntimeError('更新程序启动后已退出')
                    if attempt:
                        result = {'id': attempt, 'status': 'started'}
                        write_json(state_file, {'base': stamp, 'active': candidate, 'result': result})
                        previous, active = active, candidate
                        write_json(channel / 'result', result)
                        if previous and previous != active:
                            try:
                                slot(directory, previous).unlink(missing_ok=True)
                            except OSError:
                                logging.exception('无法清理旧版本')
                attempt = None
                while child.poll() is None and not stopping:
                    try:
                        child.wait(timeout=.5)
                    except subprocess.TimeoutExpired:
                        pass
                if stopping or child.returncode != RESTART:
                    return 0 if stopping else child.returncode
                request = read_json(channel / 'request')
                (channel / 'request').unlink()
                attempt, candidate = request['id'], request['digest']
            except (ValueError, OSError, RuntimeError):
                if not candidate:
                    raise
                logging.exception('更新启动失败，正在恢复上一版本')
                if candidate == active:
                    active = None  # A previously installed slot also failed: use the original.
                if child is not None:
                    stop_tree(child)
                result = {'id': attempt or read_json(channel / 'result').get('id'), 'status': 'rollback'}
                try:
                    slot(directory, candidate).unlink(missing_ok=True)
                    write_json(state_file, {'base': stamp, 'active': active, 'result': result})
                except (ValueError, OSError):
                    logging.exception('无法清理失败的更新')
                write_json(channel / 'result', result)
                attempt, candidate = None, active
            finally:
                if child is not None:
                    stop_tree(child)
    return 0
