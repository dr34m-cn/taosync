"""Best-effort anonymous reporting; neither tasks nor shutdown wait for a report."""
import json
import ssl
from contextlib import closing
from http.client import HTTPSConnection
from threading import BoundedSemaphore, Thread

import certifi

from common.config import anonymousStatsEnabled


_slots = BoundedSemaphore(2)


def _send(files, size):
    # A direct HTTPS request has no proxy credentials, redirects, retries or HTTP library logs.
    context = ssl.create_default_context(cafile=certifi.where())
    with closing(HTTPSConnection('taoapi.dr34m.cn', timeout=5, context=context)) as conn:
        conn.request('POST', '/v1/stats', body=json.dumps({'files': files, 'bytes': size}),
                     headers={'Content-Type': 'application/json'})
        conn.getresponse().close()


def _report(successful):
    try:
        files = size = 0
        for entry in successful:
            if entry['isPath'] == 0 and entry['type'] in (0, 2):
                files += 1
                size += entry['fileSize'] or 0
        if files and anonymousStatsEnabled():
            _send(files, size)
    except Exception:
        pass  # Discard this report, including failures in aggregation or network cleanup.
    finally:
        _slots.release()


def report(successful):
    if not successful or not anonymousStatsEnabled() or not _slots.acquire(blocking=False):
        return
    try:
        # The iterator releases the completed run's list once the worker has counted it.
        Thread(target=_report, args=(iter(successful),), name='sync-stats', daemon=True).start()
    except Exception:
        _slots.release()  # Even a thread that could not start must not affect the task.
