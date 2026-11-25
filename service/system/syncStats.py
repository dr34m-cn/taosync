"""Best-effort reporting of a single completed run; never queue historical tasks."""
from concurrent.futures import ThreadPoolExecutor

import requests

from common.config import getConfig


_ENDPOINT = 'https://taoapi.dr34m.cn/v1/stats'
_sender = ThreadPoolExecutor(max_workers=2, thread_name_prefix='sync-stats')


def _enabled():
    return getConfig()['server']['anonymous_stats']


def _send(files, size):
    if not _enabled():  # A queued report must also respect a subsequent opt-out.
        return
    try:
        with requests.Session() as session:
            session.trust_env = False  # Never attach credentials from .netrc.
            with session.post(_ENDPOINT, json={'files': files, 'bytes': size}, timeout=(3, 5),
                              allow_redirects=False, stream=True):
                pass
    except requests.RequestException:
        pass  # Do not retry: a lost response may follow a successful increment.


def report(successful):
    if not _enabled():
        return
    files = size = 0
    for entry in successful:
        if entry['isPath'] == 0 and entry['type'] in (0, 2):
            files += 1
            size += entry['fileSize'] or 0
    if files:
        _sender.submit(_send, files, size)
