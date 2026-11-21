"""Wire format shared by the build, the public mirror and the updater."""
import json
import re
from datetime import datetime


MAX_MANIFEST_BYTES = 16 * 1024 * 1024
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}')
SHA256 = re.compile(r'[a-f0-9]{64}')
FIELDS = ('version', 'arch', 'sha256')


def parse_manifest(raw):
    return [row[:3] for row in parse_builds(raw)]


def parse_builds(raw):
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('manifest too large')
    try:
        doc = json.loads(raw.decode('utf-8'))
    except RecursionError as exc:
        raise ValueError('invalid manifest') from exc
    if (not isinstance(doc, dict) or type(doc.get('schema')) is not int or doc['schema'] != 1
            or not isinstance(doc.get('entries'), list)):
        raise ValueError('invalid manifest')
    rows = []
    published = doc.get('publishedAt', {})
    if not isinstance(published, dict):
        raise ValueError('invalid publication dates')
    for item in doc['entries']:
        if not isinstance(item, dict) or set(item) != set(FIELDS):
            raise ValueError('invalid manifest entry')
        row = tuple(item[k] for k in FIELDS)
        if not all(isinstance(s, str) and pattern.fullmatch(s)
                   for s, pattern in zip(row, (LABEL, LABEL, SHA256))):
            raise ValueError('invalid manifest entry')
        stamp = published.get('/'.join(row))
        if stamp is not None:
            if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', stamp):
                raise ValueError('invalid publication date')
            datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
        rows.append((*row, stamp))
    return rows


def encode_manifest(rows):
    builds = {}
    for version, arch, sha, *date in rows:
        key = (version, arch, sha)
        builds[key] = builds.get(key) or next(iter(date), None)
    # Released clients require exactly three fields per entry, but ignore top-level metadata.
    doc = {'schema': 1, 'entries': [dict(zip(FIELDS, key)) for key in builds],
           'publishedAt': {'/'.join(key): date for key, date in builds.items() if date}}
    raw = (json.dumps(doc, indent=2) + '\n').encode('utf-8')
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('manifest too large')
    return raw
