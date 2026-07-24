import re
import sys
from pathlib import Path


NAME_PATTERN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def canonical_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_lines(path):
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        match = NAME_PATTERN.match(line)
        if not match:
            raise ValueError(f"{path}:{line_number}: unsupported requirement: {raw_line}")
        yield line_number, line, canonical_name(match.group(1))


def main():
    direct_path = Path(sys.argv[1] if len(sys.argv) > 1 else "requirements.in")
    lock_path = Path(sys.argv[2] if len(sys.argv) > 2 else "requirements.txt")

    direct_names = {name for _, _, name in requirement_lines(direct_path)}
    lock_entries = list(requirement_lines(lock_path))
    lock_names = {name for _, _, name in lock_entries}

    unpinned = [f"{lock_path}:{line_number}: {line}" for line_number, line, _ in lock_entries if "==" not in line]
    missing = sorted(direct_names - lock_names)

    if unpinned or missing:
        if unpinned:
            print("Lock entries must use exact == versions:", file=sys.stderr)
            print("\n".join(unpinned), file=sys.stderr)
        if missing:
            print("Direct dependencies missing from the lock: " + ", ".join(missing), file=sys.stderr)
        return 1

    print(f"Verified {len(direct_names)} direct and {len(lock_names)} locked dependencies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
