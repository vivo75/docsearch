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
  # crawled checkouts (private GitHub sources: nosql-docs, azure-security-docs): fetch today's
  # seventh of the pages, then the update below diffs the checkouts in. Never fails the run.
  .venv/bin/python eval/crawl_learn.py --service all --shard auto || echo "crawl failed"
  .venv/bin/docsearch update --pull --canary
  # report of what the update brought in (git changes per area, summarised by the local Gemma); never fails the run
  rep="data/reports/changes-$(basename "$(readlink data/current.db)" .db).md"
  [ -e "$rep" ] || .venv/bin/docsearch changes --summarize --out "$rep" > /dev/null || echo "changes report failed"
  # weekly consistency check (Sunday): fresh parse of a random sample must match the index
  if [ "$(date +%u)" = "7" ]; then echo "--- verify"; .venv/bin/docsearch verify --sample 300; fi
} >> data/nightly.log 2>&1
