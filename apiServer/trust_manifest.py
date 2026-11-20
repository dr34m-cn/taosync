"""Wire format shared by the build, the public mirror and the updater."""
import json
import re


MAX_MANIFEST_BYTES = 16 * 1024 * 1024
LABEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,127}')
SHA256 = re.compile(r'[a-f0-9]{64}')
FIELDS = ('version', 'arch', 'sha256')


def parse_manifest(raw):
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
    for item in doc['entries']:
        if not isinstance(item, dict) or set(item) != set(FIELDS):
            raise ValueError('invalid manifest entry')
        row = tuple(item[k] for k in FIELDS)
        if not all(isinstance(s, str) and pattern.fullmatch(s)
                   for s, pattern in zip(row, (LABEL, LABEL, SHA256))):
            raise ValueError('invalid manifest entry')
        rows.append(row)
    return rows


def encode_manifest(rows):
    entries = [dict(zip(FIELDS, row)) for row in dict.fromkeys(rows)]
    raw = (json.dumps({'schema': 1, 'entries': entries}, indent=2) + '\n').encode('utf-8')
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError('manifest too large')
    return raw
