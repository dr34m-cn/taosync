#!/usr/bin/env bash
# Fast-forward only. A concurrent winner becomes the base of our next attempt.
set -euo pipefail
delta=$1
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
for attempt in {1..10}; do
  inputs=()
  parent=()
  if git ls-remote --exit-code origin refs/heads/auth > /dev/null; then
    git fetch --quiet --no-tags origin refs/heads/auth
    base=$(git rev-parse FETCH_HEAD)
    parent=(-p "$base")
    if git cat-file -e "$base:auth.json" 2>/dev/null; then
      git show "$base:auth.json" > "$tmp/prev-auth.json"
      inputs+=("$tmp/prev-auth.json")
    fi
    if git cat-file -e "$base:auth-dev.json" 2>/dev/null; then
      git show "$base:auth-dev.json" > "$tmp/prev-dev.json"
      inputs+=("$tmp/prev-dev.json")
    fi
  elif [[ $? != 2 ]]; then
    exit 1
  fi
  inputs+=("$delta")
  python3 scripts/release-checksums.py split "$tmp/auth.json" "$tmp/auth-dev.json" "$tmp/latest.json" "${inputs[@]}"
  auth_json=$(git hash-object -w "$tmp/auth.json")
  dev_json=$(git hash-object -w "$tmp/auth-dev.json")
  latest_json=$(git hash-object -w "$tmp/latest.json")
  html=$(git hash-object -w apiServer/index.html)
  icon=$(git hash-object -w logo.ico)
  tree=$(printf '100644 blob %s\tauth-dev.json\n100644 blob %s\tauth.json\n100644 blob %s\tindex.html\n100644 blob %s\tlatest.json\n100644 blob %s\tlogo.ico\n' \
    "$dev_json" "$auth_json" "$html" "$latest_json" "$icon" | git mktree)
  if [[ -n "${base:-}" && $(git rev-parse "$base^{tree}") == "$tree" ]]; then
    revision=$base
  else
    revision=$(git commit-tree "$tree" "${parent[@]}" -m "Register builds: $GITHUB_RUN_ID/$GITHUB_RUN_ATTEMPT")
    if ! git push origin "$revision:refs/heads/auth"; then
      sleep "$attempt"
      continue
    fi
  fi
  echo "revision=$revision" >> "$GITHUB_OUTPUT"
  exit 0
done
echo 'Could not fast-forward auth after repeated attempts' >&2
exit 1
