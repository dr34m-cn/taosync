"""Wire format shared by the build, the public mirror and the updater."""
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit


MAX_MANIFEST_BYTES = 16 * 1024 * 1024
STABLE_DOWNLOAD_RETENTION = 3
DEV_DOWNLOAD_RETENTION = 2
MAX_DOWNLOAD_SOURCES = 32
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}')
LOCALE_KEY = re.compile(r'[A-Za-z0-9_-]{2,32}')
STABLE_VERSION = re.compile(r'v?\d+(?:\.\d+)*')
SHA256 = re.compile(r'[a-f0-9]{64}')
TEMPLATE_PLACEHOLDER = re.compile(r'\{([^{}]+)\}')
ALLOWED_PLACEHOLDERS = frozenset({'version', 'filename', 'arch'})
FIELDS = ('version', 'arch', 'sha256')
CHANNELS = ('stable', 'dev')
DEFAULT_DOWNLOAD_SOURCES = {
    'stable': [
        {
            'id': 'github',
            'name': 'GitHub Release',
            'labels': {'zh-CN': 'GitHub Release', 'en': 'GitHub Release'},
            'urlTemplate': 'https://github.com/dr34m-cn/taosync/releases/download/{version}/{filename}',
        },
        {
            'id': 'r2',
            'name': 'Cloudflare R2',
            'labels': {'zh-CN': 'Cloudflare R2', 'en': 'Cloudflare R2'},
            'urlTemplate': 'https://cdn.20240303.xyz/taosync-release/{version}/{filename}',
        },
    ],
    'dev': [
        {
            'id': 'r2',
            'name': 'Cloudflare R2',
            'labels': {'zh-CN': 'Cloudflare R2', 'en': 'Cloudflare R2'},
            'urlTemplate': 'https://cdn.20240303.xyz/taosync-release/dev/{version}/{filename}',
        },
    ],
}


def is_stable_version(version):
    return isinstance(version, str) and bool(STABLE_VERSION.fullmatch(version))


def stable_version_key(version):
    return tuple(int(part) for part in version.lstrip('v').split('.'))


def natural_version_key(version):
    parts = re.split(r'(\d+)', str(version))
    return tuple((1, int(part)) if part.isdigit() else (0, part.lower()) for part in parts if part)


def _valid_text(value, limit=128):
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or len(cleaned) > limit or any(ord(ch) < 32 or ord(ch) == 127 for ch in cleaned):
        return None
    return cleaned


def _validate_https_url(url, limit=512):
    if not isinstance(url, str) or not url or len(url) > limit:
        raise ValueError('invalid download url')
    if any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise ValueError('invalid download url')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('invalid download url')
    return url


def render_download_url(template, *, version, filename='', arch=''):
    if not isinstance(template, str):
        raise ValueError('invalid url template')
    values = {
        'version': quote(str(version), safe=''),
        'filename': quote(str(filename), safe=''),
        'arch': quote(str(arch), safe=''),
    }

    def replace(match):
        key = match.group(1)
        if key not in ALLOWED_PLACEHOLDERS:
            raise ValueError('invalid url template placeholder')
        return values[key]

    rendered = TEMPLATE_PLACEHOLDER.sub(replace, template)
    if '{' in rendered or '}' in rendered:
        raise ValueError('invalid url template')
    return _validate_https_url(rendered, limit=1024)


def normalize_download_source(item):
    if not isinstance(item, dict):
        raise ValueError('invalid download source')
    source_id = item.get('id')
    if not isinstance(source_id, str) or not LABEL.fullmatch(source_id) or source_id.lower() == 'auto':
        raise ValueError('invalid download source id')
    name = _valid_text(item.get('name'))
    if not name:
        raise ValueError('invalid download source name')
    template = item.get('urlTemplate')
    if not isinstance(template, str) or len(template) > 512:
        raise ValueError('invalid download source template')
    placeholders = TEMPLATE_PLACEHOLDER.findall(template)
    if not placeholders or any(key not in ALLOWED_PLACEHOLDERS for key in placeholders):
        raise ValueError('invalid download source template')
    if 'filename' not in placeholders and 'arch' not in placeholders:
        raise ValueError('invalid download source template')
    render_download_url(template, version='v1.0.0', filename='taoSync-v1.0.0-linux-amd64.tar.gz', arch='linux-amd64')
    normalized = {'id': source_id, 'name': name, 'urlTemplate': template}
    labels = item.get('labels')
    if labels is not None:
        if not isinstance(labels, dict) or len(labels) > 16:
            raise ValueError('invalid download source labels')
        clean_labels = {}
        for locale_key, text in labels.items():
            if not isinstance(locale_key, str) or not LOCALE_KEY.fullmatch(locale_key):
                raise ValueError('invalid download source labels')
            clean_text = _valid_text(text)
            if not clean_text:
                raise ValueError('invalid download source labels')
            clean_labels[locale_key] = clean_text
        if clean_labels:
            normalized['labels'] = clean_labels
    return normalized


def normalize_download_sources(raw):
    if not isinstance(raw, dict) or not set(raw).issubset(set(CHANNELS)):
        raise ValueError('invalid download sources')
    result = {}
    for channel in CHANNELS:
        items = raw.get(channel, [])
        if not isinstance(items, list) or len(items) > MAX_DOWNLOAD_SOURCES:
            raise ValueError('invalid download sources')
        seen = set()
        normalized_items = []
        for item in items:
            normalized = normalize_download_source(item)
            if normalized['id'] in seen:
                raise ValueError('duplicate download source id')
            seen.add(normalized['id'])
            normalized_items.append(normalized)
        result[channel] = normalized_items
    return result


def load_download_sources(path=None):
    source_path = Path(path) if path is not None else Path(__file__).with_name('download_sources.json')
    if path is None and not source_path.is_file():
        return normalize_download_sources(DEFAULT_DOWNLOAD_SOURCES)
    data = json.loads(source_path.read_text(encoding='utf-8'))
    return normalize_download_sources(data)


def artifact_filename(version, arch):
    if not isinstance(version, str) or not LABEL.fullmatch(version):
        return None
    if not isinstance(arch, str) or not LABEL.fullmatch(arch):
        return None
    if arch.startswith('windows-') or arch.startswith('linux-StaticX-'):
        return f'taoSync-{version}-{arch}.zip'
    if arch.startswith('darwin-') or arch.startswith('linux-'):
        return f'taoSync-{version}-{arch}.tar.gz'
    if arch == 'android-arm64-v8a+armeabi-v7a':
        return f'taoSync-{version}-android-debug.apk'
    return None


def _group_channel_versions(rows, channel, sources, limit):
    grouped = {}
    for version, arch, _sha, *date in rows:
        stamp = next(iter(date), None)
        entry = grouped.setdefault(version, {'publishedAt': None, 'assets': {}})
        if stamp and (entry['publishedAt'] is None or stamp > entry['publishedAt']):
            entry['publishedAt'] = stamp
        filename = artifact_filename(version, arch)
        if filename:
            entry['assets'][arch] = filename
    if channel == 'stable':
        ordered_versions = sorted(
            grouped,
            key=lambda ver: (stable_version_key(ver), grouped[ver]['publishedAt'] or '', ver),
            reverse=True,
        )[:limit]
    else:
        ordered_versions = sorted(
            grouped,
            key=lambda ver: (grouped[ver]['publishedAt'] or '', natural_version_key(ver), ver),
            reverse=True,
        )[:limit]
    items = []
    for version in ordered_versions:
        info = grouped[version]
        item = {
            'version': version,
            'channel': channel,
            'assets': dict(sorted(info['assets'].items())),
            'sources': [dict(source, labels=dict(source['labels'])) if 'labels' in source else dict(source)
                        for source in sources],
        }
        if info['publishedAt'] is not None:
            item['publishedAt'] = info['publishedAt']
        items.append(item)
    return items


def build_downloads_catalog(stable_rows, dev_rows, download_sources=None):
    sources = normalize_download_sources(
        DEFAULT_DOWNLOAD_SOURCES if download_sources is None else download_sources
    )
    versions = (
        _group_channel_versions(stable_rows, 'stable', sources['stable'], STABLE_DOWNLOAD_RETENTION)
        + _group_channel_versions(dev_rows, 'dev', sources['dev'], DEV_DOWNLOAD_RETENTION)
    )
    return {'sources': sources, 'versions': versions}


def _validate_stamp(stamp):
    if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', stamp):
        raise ValueError('invalid publication date')
    datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
    return stamp


def normalize_downloads_catalog(raw):
    if not isinstance(raw, dict):
        raise ValueError('invalid downloads catalog')
    sources = normalize_download_sources(raw.get('sources', {})) if 'sources' in raw else None
    raw_versions = raw.get('versions')
    if not isinstance(raw_versions, list) or len(raw_versions) > 64:
        raise ValueError('invalid downloads catalog')
    seen_versions = set()
    versions = []
    for item in raw_versions:
        if not isinstance(item, dict):
            raise ValueError('invalid downloads version')
        version = item.get('version')
        channel = item.get('channel')
        if not isinstance(version, str) or not LABEL.fullmatch(version) or version in seen_versions:
            raise ValueError('invalid downloads version')
        if channel not in CHANNELS:
            raise ValueError('invalid downloads channel')
        seen_versions.add(version)
        raw_assets = item.get('assets')
        if not isinstance(raw_assets, dict) or len(raw_assets) > 64:
            raise ValueError('invalid downloads assets')
        assets = {}
        for arch, filename in sorted(raw_assets.items()):
            if not isinstance(arch, str) or not LABEL.fullmatch(arch):
                raise ValueError('invalid downloads assets')
            if not isinstance(filename, str) or not LABEL.fullmatch(filename) or '..' in filename:
                raise ValueError('invalid downloads assets')
            assets[arch] = filename
        raw_sources = item.get('sources')
        if not isinstance(raw_sources, list) or len(raw_sources) > MAX_DOWNLOAD_SOURCES:
            raise ValueError('invalid downloads sources')
        seen_ids = set()
        item_sources = []
        for source in raw_sources:
            normalized = normalize_download_source(source)
            if normalized['id'] in seen_ids:
                raise ValueError('duplicate download source id')
            seen_ids.add(normalized['id'])
            item_sources.append(normalized)
        entry = {
            'version': version,
            'channel': channel,
            'assets': assets,
            'sources': item_sources,
        }
        if 'publishedAt' in item and item['publishedAt'] is not None:
            entry['publishedAt'] = _validate_stamp(item['publishedAt'])
        versions.append(entry)
    result = {'versions': versions}
    if sources is not None:
        result['sources'] = sources
    return result


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


def parse_download_sources(raw):
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('manifest too large')
    try:
        doc = json.loads(raw.decode('utf-8'))
    except RecursionError as exc:
        raise ValueError('invalid manifest') from exc
    if not isinstance(doc, dict) or 'downloadSources' not in doc:
        return None
    return normalize_download_sources(doc['downloadSources'])


def parse_latest_details(raw):
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
    downloads = None
    if 'downloads' in doc and doc['downloads'] is not None:
        downloads = normalize_downloads_catalog(doc['downloads'])
    return version, [row[:3] for row in rows], downloads


def parse_latest(raw):
    version, rows, _downloads = parse_latest_details(raw)
    return version, rows


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
            _validate_stamp(stamp)
        rows.append((*row, stamp))
    return rows


def encode_manifest(rows, *, version=None, download_sources=None, downloads=None):
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
    if download_sources is not None:
        doc['downloadSources'] = normalize_download_sources(download_sources)
    if downloads is not None:
        doc['downloads'] = normalize_downloads_catalog(downloads)
    raw = (json.dumps(doc, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('manifest too large')
    return raw
