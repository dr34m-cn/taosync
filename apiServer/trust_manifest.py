"""Wire format shared by the build, the public mirror and the updater."""
import json
import re
from datetime import datetime


MAX_MANIFEST_BYTES = 16 * 1024 * 1024
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}')
STABLE_VERSION = re.compile(r'v?\d+(?:\.\d+)*')
SHA256 = re.compile(r'[a-f0-9]{64}')
FIELDS = ('version', 'arch', 'sha256')


def is_stable_version(version):
    return isinstance(version, str) and bool(STABLE_VERSION.fullmatch(version))


def stable_version_key(version):
    return tuple(int(part) for part in version.lstrip('v').split('.'))


def split_builds(rows):
    """Deduplicate builds and partition into (stable, dev, latest_version, latest_rows)."""
    builds = {}
    for version, arch, sha, *date in rows:
        key = (version, arch, sha)
        builds[key] = builds.get(key) or next(iter(date), None)
    ordered = [(*key, stamp) for key, stamp in builds.items()]
    stable = [row for row in ordered if is_stable_version(row[0])]
    dev = [row for row in ordered if not is_stable_version(row[0])]
    latest_version = None
    latest = []
    if stable:
        latest_key = max(stable_version_key(row[0]) for row in stable)
        latest_version = [row[0] for row in stable if stable_version_key(row[0]) == latest_key][-1]
        latest = [row for row in stable if row[0] == latest_version]
    return stable, dev, latest_version, latest


def parse_manifest(raw):
    return [row[:3] for row in parse_builds(raw)]


def parse_latest(raw):
    rows = parse_builds(raw)
    doc = json.loads(raw.decode('utf-8'))
    version = doc.get('version')
    if version is not None:
        if not isinstance(version, str) or not LABEL.fullmatch(version):
            raise ValueError('invalid latest version')
        if not rows or any(row[0] != version for row in rows):
            raise ValueError('latest version does not match entries')
    elif rows:
        versions = {row[0] for row in rows}
        if len(versions) == 1:
            version = next(iter(versions))
        else:
            stable = [v for v in versions if is_stable_version(v)]
            if not stable:
                raise ValueError('ambiguous latest manifest')
            version = max(stable, key=stable_version_key)
    return version, [row[:3] for row in rows]


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


def encode_manifest(rows, *, version=None):
    builds = {}
    for item_version, arch, sha, *date in rows:
        key = (item_version, arch, sha)
        builds[key] = builds.get(key) or next(iter(date), None)
    # Released clients require exactly three fields per entry, but ignore top-level metadata.
    doc = {'schema': 1}
    if version is not None:
        if not isinstance(version, str) or not LABEL.fullmatch(version):
            raise ValueError('invalid manifest version')
        doc['version'] = version
    doc['entries'] = [dict(zip(FIELDS, key)) for key in builds]
    doc['publishedAt'] = {'/'.join(key): date for key, date in builds.items() if date}
    raw = (json.dumps(doc, indent=2) + '\n').encode('utf-8')
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('manifest too large')
    return raw
