import hashlib
import json
import re


def contentHashes(metadata):
    """Normalize explicitly labelled backend whole-file hashes; opaque version markers are not digests."""
    valid = {}
    for key, value in metadata.get('contentHashes', {}).items():
        algorithm = str(key).lower().replace('-', '')
        length = {'md5': 32, 'sha1': 40, 'sha256': 64, 'sha512': 128}.get(algorithm)
        if length and isinstance(value, str) and len(value) == length and re.fullmatch('[0-9a-fA-F]+', value):
            valid[algorithm] = value.lower()
    return valid


def contentHashesDiffer(source, target):
    sourceHashes = source.get('contentHashes', {})
    targetHashes = target.get('contentHashes', {})
    return any(sourceHashes[key] != targetHashes[key] for key in sourceHashes.keys() & targetHashes.keys())


def fileFingerprint(namespace, *components):
    """Build an opaque, deterministic version marker from backend metadata."""
    if not any(component not in (None, "", {}, []) for component in components):
        return None
    payload = json.dumps(
        [str(namespace), *components],
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "{}:sha256:{}".format(
        namespace, hashlib.sha256(payload).hexdigest()
    )
