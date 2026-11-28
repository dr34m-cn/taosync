"""Upload release artifacts to Cloudflare R2 and enforce per-channel version retention."""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apiServer.trust_manifest import LABEL, is_stable_version, natural_version_key, stable_version_key

BASE_PREFIX = 'taosync-release'
KEEP_STABLE = 3
KEEP_DEV = 2


def classify_version(version):
    if not isinstance(version, str) or not LABEL.fullmatch(version) or version.lower() == 'dev' or '..' in version:
        raise ValueError(f'Invalid release version: {version!r}')
    return 'stable' if is_stable_version(version) else 'dev'


def target_prefix(version, base_prefix=BASE_PREFIX):
    channel = classify_version(version)
    base = base_prefix.strip('/')
    if channel == 'stable':
        return f'{base}/{version}/'
    return f'{base}/dev/{version}/'


def select_retention_state(objects, *, current_version=None, keep_stable=KEEP_STABLE, keep_dev=KEEP_DEV,
                           base_prefix=BASE_PREFIX):
    base = base_prefix.strip('/')
    root = f'{base}/'
    stable_versions = {}
    dev_versions = {}
    for item in objects:
        key = item.get('Key') if isinstance(item, dict) else None
        if not isinstance(key, str) or not key.startswith(root):
            continue
        rel = key[len(root):]
        parts = rel.split('/')
        stamp = str(item.get('LastModified') or '')
        if parts[0] == 'dev':
            if len(parts) >= 3 and parts[1]:
                ver = parts[1]
                if ver not in dev_versions or stamp > dev_versions[ver]:
                    dev_versions[ver] = stamp
        elif len(parts) >= 2 and parts[0] and is_stable_version(parts[0]):
            ver = parts[0]
            if ver not in stable_versions or stamp > stable_versions[ver]:
                stable_versions[ver] = stamp

    if current_version:
        if is_stable_version(current_version):
            stable_versions.setdefault(current_version, '')
        else:
            dev_versions.setdefault(current_version, '')

    stable_ordered = sorted(
        stable_versions,
        key=lambda ver: (stable_version_key(ver), stable_versions[ver], ver),
        reverse=True,
    )
    current_dev = current_version if current_version and not is_stable_version(current_version) else None
    dev_ordered = sorted(
        dev_versions,
        key=lambda ver: (ver == current_dev, dev_versions[ver], natural_version_key(ver), ver),
        reverse=True,
    )
    kept_stable = stable_ordered[:keep_stable]
    kept_dev = dev_ordered[:keep_dev]
    pruned = [f'{base}/{ver}/' for ver in stable_ordered[keep_stable:]]
    pruned.extend(f'{base}/dev/{ver}/' for ver in dev_ordered[keep_dev:])
    present_versions = kept_stable + kept_dev
    return pruned, present_versions


def select_pruned_prefixes(objects, *, current_version=None, keep_stable=KEEP_STABLE, keep_dev=KEEP_DEV,
                           base_prefix=BASE_PREFIX):
    pruned, _present = select_retention_state(
        objects,
        current_version=current_version,
        keep_stable=keep_stable,
        keep_dev=keep_dev,
        base_prefix=base_prefix,
    )
    return pruned


def _aws_env(access_key_id, secret_access_key):
    env = os.environ.copy()
    env.update({
        'AWS_ACCESS_KEY_ID': access_key_id,
        'AWS_SECRET_ACCESS_KEY': secret_access_key,
        'AWS_DEFAULT_REGION': 'auto',
        'AWS_EC2_METADATA_DISABLED': 'true',
        'AWS_REQUEST_CHECKSUM_CALCULATION': 'when_required',
        'AWS_RESPONSE_CHECKSUM_VALIDATION': 'when_required',
    })
    return env


def _run_aws(args, env, capture=False):
    result = subprocess.run(
        ['aws', *args],
        env=env,
        check=True,
        text=True,
        capture_output=capture,
    )
    return result.stdout if capture else ''


def list_objects(bucket, endpoint, prefix, env):
    objects = []
    token = None
    while True:
        args = [
            's3api', 'list-objects-v2',
            '--bucket', bucket,
            '--prefix', prefix,
            '--endpoint-url', endpoint,
            '--output', 'json',
        ]
        if token:
            args.extend(['--continuation-token', token])
        raw = _run_aws(args, env, capture=True).strip()
        data = json.loads(raw) if raw else {}
        objects.extend(data.get('Contents') or [])
        if not data.get('IsTruncated'):
            break
        token = data.get('NextContinuationToken')
        if not token:
            break
    return objects


def publish_to_r2(dist_dir, version, *, endpoint, bucket, access_key_id, secret_access_key,
                  base_prefix=BASE_PREFIX, keep_stable=KEEP_STABLE, keep_dev=KEEP_DEV, receipt_path=None):
    dist_path = Path(dist_dir)
    if not dist_path.is_dir() or not any(dist_path.iterdir()):
        raise ValueError(f'No release files found in {dist_dir}')
    endpoint = endpoint.strip().rstrip('/')
    bucket = bucket.strip().strip('/')
    if not endpoint.startswith('https://') or not bucket:
        raise ValueError('R2_ENDPOINT (https://...) and R2_BUCKET are required')
    if not access_key_id or not secret_access_key:
        raise ValueError('R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY are required')

    prefix = target_prefix(version, base_prefix=base_prefix)
    env = _aws_env(access_key_id, secret_access_key)
    destination = f's3://{bucket}/{prefix}'
    print(f'Uploading {dist_path} -> {destination}')
    _run_aws([
        's3', 'sync', str(dist_path), destination,
        '--endpoint-url', endpoint,
        '--delete',
        '--cache-control', 'public, max-age=3600',
        '--no-progress',
    ], env)

    objects = list_objects(bucket, endpoint, f'{base_prefix.strip("/")}/', env)
    pruned, present_versions = select_retention_state(
        objects,
        current_version=version,
        keep_stable=keep_stable,
        keep_dev=keep_dev,
        base_prefix=base_prefix,
    )
    for old_prefix in pruned:
        print(f'Pruning old R2 release prefix: s3://{bucket}/{old_prefix}')
        _run_aws([
            's3', 'rm', f's3://{bucket}/{old_prefix}',
            '--recursive',
            '--endpoint-url', endpoint,
        ], env)
    if receipt_path:
        target = Path(receipt_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        receipt = {
            'source': 'r2',
            'version': version,
            'presentVersions': present_versions,
        }
        target.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return prefix, pruned


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    receipt_path = None
    if '--receipt' in args:
        idx = args.index('--receipt')
        if idx + 1 >= len(args):
            raise SystemExit('Usage: publish-r2.py <dist_dir> <version> [--receipt <path>]')
        receipt_path = args[idx + 1]
        del args[idx:idx + 2]
    if len(args) != 2:
        raise SystemExit('Usage: publish-r2.py <dist_dir> <version> [--receipt <path>]')
    dist_dir, version = args
    publish_to_r2(
        dist_dir,
        version,
        endpoint=os.environ.get('R2_ENDPOINT', ''),
        bucket=os.environ.get('R2_BUCKET', ''),
        access_key_id=os.environ.get('R2_ACCESS_KEY_ID', ''),
        secret_access_key=os.environ.get('R2_SECRET_ACCESS_KEY', ''),
        receipt_path=receipt_path,
    )


if __name__ == '__main__':
    main()
