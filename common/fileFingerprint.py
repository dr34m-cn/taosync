import hashlib
import json


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
