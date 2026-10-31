#!/usr/bin/env bash
# Nightly: pull every repo, patch the index from the git changes, run canaries, atomically publish.
# A failed run leaves the live index untouched. flock prevents overlapping runs. Exit status is non-zero on failure.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
exec 9>data/.update.lock
flock -n 9 || { echo "$(date -Is) another update is running" >> data/nightly.log; exit 0; }
{
  echo "=== $(date -Is) update"
  uv run docsearch update --pull --canary
  # weekly consistency check (Sunday): fresh parse of a random sample must match the index
  if [ "$(date +%u)" = "7" ]; then echo "--- verify"; uv run docsearch verify --sample 300; fi
} >> data/nightly.log 2>&1
