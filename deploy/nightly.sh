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
  # Terraform azurerm provider docs: pull the upstream clone and convert (never fails the run)
  .venv/bin/python eval/convert_azurerm.py --pull || echo "azurerm convert failed"
  .venv/bin/python eval/convert_aks_releases.py --pull || echo "aks release notes convert failed"
  .venv/bin/python eval/convert_k8s.py --pull || echo "kubernetes docs convert failed"
  .venv/bin/docsearch update --pull --canary
  # the exact-vector matrix (.npy) must agree with the index that is now live: sizes, rowid set, sampled rows (never fails the run, but says so)
  .venv/bin/docsearch vecmat --check || echo "vecmat check FAILED: see the report above (rebuild with: docsearch vecmat)"
  # the MCP server reads repos.toml once at start (grep_docs roots, repo weights): restart it if the file changed since
  started=$(date -d "$(systemctl --user show docsearch-mcp -p ActiveEnterTimestamp --value)" +%s 2>/dev/null || echo 0)
  if [ "$(stat -c %Y repos.toml)" -gt "$started" ]; then systemctl --user restart docsearch-mcp || echo "mcp restart failed"; fi
  # report of what the update brought in (git changes per area, summarised by the local Gemma); never fails the run
  rep="data/reports/changes-$(basename "$(readlink data/current.db)" .db).md"
  [ -e "$rep" ] || .venv/bin/docsearch changes --summarize --out "$rep" > /dev/null || echo "changes report failed"
  # weekly consistency check (Sunday): fresh parse of a random sample must match the index
  if [ "$(date +%u)" = "7" ]; then echo "--- verify"; .venv/bin/docsearch verify --sample 300; fi
} >> data/nightly.log 2>&1
