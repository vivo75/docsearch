# docsearch — handoff (state as of 2026-11-01)

Implements `../option-2-local-hybrid-index.md`. Everything lives in this directory; `data/` (gitignored) holds the index.
Run tests: `uv run pytest -q` (83 pass). No background jobs are running; no llama-server is left running.

## Reconstructed includes (2026-11-01) — read before touching `reusable-content`
`/mnt/D500G/space/Microsoft/reusable-content/` and `.../azure-dev-docs-pr/` are **NOT the real repos**: stand-ins (15 files: 9 in reusable-content, 6 terraform in azure-dev-docs-pr) rebuilt from the
rendered Learn pages of the most-used unresolved includes (free-trial note, updated-for-az, both azure-cli-prepare-your-environment, AKS preview callout,
ARM and Bicep intros, cloud-shell-try-it, terraform-init, plus the terraform family: abstract, plan, plan-notes, apply-plan, plan-destroy). Each file has `reconstructed: true` + source URLs in frontmatter (stripped at index time, so the
index text is unmarked); each directory has `RECONSTRUCTED.md` and `manifest.json`. They are not git repos and not in `repos.toml`. Known weak spots: link URLs lost,
markup/code fences partly inferred. Skipped on purpose: `horz-monitor-ref-metrics-tableheader.md` (header boundary unclear). To undo: delete both directories and run `docsearch build`
(`docsearch update` would not notice the removal: it only heals newly resolvable includes, not vanished ones). If the real repos are ever cloned, replace the directories and `docsearch build`.
- `docsearch update` now **heals** pages: `_heal_unresolved` (update.py) re-resolves every `*_unresolved` page and reprocesses those that gained a dependency not in `deps`
  (no git change needed; ~1,700 page reads). First run: 977 pages, 12,340 chunks, 1,489 embedded; index `index-20261101-195217309.db` (live); previous index kept (`pre` in compare.py).
  Terraform batch: live index `index-20261101-210737332.db` (`h1` in compare.py = the one before); qinc R@5 .417 -> .667 on 72 questions. qset2 `test` no-regression check was still running at commit time: see `data/logs/heal2-compare.log`.
- Results: no change on qset2 (test/dev), large gain on the new include-targeted set qinc (R@5 .167 -> .604); details in eval/README.md ("qinc").
- Method (reusable for more includes, ~399 distinct unresolved includes, the 10 used cover ~1,280 of 1,752 occurrences): list unresolved includes with their pages (IncludeResolver on flagged docs),
  fetch 3 rendered pages per include at 1 request / 0.8 s, give source+rendered text to a Haiku agent to extract the text at the marker, check the 3 extractions agree. Avoid tables/tab-heavy includes.
- Next: more includes (azure-dev-docs-pr terraform-* family, horz-monitor-ref-* once the table boundary is understood), then re-run `compare.py` on qset2 + qinc.

## What exists and works
| area | where |
|---|---|
| Parsing, includes, snippets, variants, URLs, chunking | `src/docsearch/{frontmatter,includes,snippets,variants,urls,normalize,chunker,pipeline}.py` |
| Full build (parallel parse, resumable embed, health checks, atomic swap) | `docsearch build` (`build.py`, `store.py`, `embed.py`) |
| Published index | `data/current.db` -> `index-20261031-144038161.db` (267,518 chunks, 14 repos; see 'Corpus additions') |
| Retrieval | `search.py`: BM25 + identifier FTS + sqlite-vec, RRF, boosts, variant grouping, optional rerank + query expansion |
| MCP server | `docsearch serve` (`server.py`): search_docs, expand, read_doc, outline_doc, browse, grep_docs. registered in Claude Code (user scope, 2026-11-01) |
| Nightly incremental update | `docsearch update [--pull] [--dry-run] [--canary]`, `docsearch verify`; `deploy/nightly.sh` + systemd units (NOT installed) |
| Eval | `eval/` (58 questions, README with results/caveats, scripts `run_eval.py`, `rerank_eval.py`, `expand_eval.py`) |

Registered 2026-11-01 with `claude mcp add --scope user docsearch -- /mnt/D500G/space/Microsoft/LLM/docsearch/.venv/bin/docsearch serve`
Nightly timer: installed 2026-11-01 from `deploy/` (see header of `deploy/docsearch-update.service`).

## Decisions taken
- Embeddings: nomic-embed-text-v1.5 Q4 via llama-server on Vulkan0 (RX 6600). Restart the server every ~15k chunks (it slows ~2x with uptime).
- Reranker: **bge-reranker-v2-m3 Q8**, top 10, fused with original rank at equal weight (`SERVER_CONFIG` in `server.py`), 1,200 chars per chunk. Disable with `DOCSEARCH_RERANK=off`.
- Rejected: Qwen3-Reranker-4B (no better, 5-8 s), jina-reranker-v3 (returns 0 via llama.cpp), int8/binary vectors (no speedup / lost precision), whole-corpus contextual retrieval with Gemma (~92 h).
- Priority from the user: precision and meaningful results over latency. Current warm latency ~1.8 s (rerank ~1.2 s, vector ~0.4 s, lexical ~0.2 s).

## Eval numbers (52 answerable; strict gold / lenient = with pooled judgments)
default hybrid R@5 .846/.923, MRR .692/.800 | + rerank R@1 .635/.750, MRR .730-.738/.830 | Learn MCP R@5 .769 | grep proxy .385.
Query expansion with Gemma (strict): vector-side expansion **R@5 .904, R@10 .942, variant acc 1.0, unanswerable AUC .779** (best recall gain so far);
both sides + rerank MRR .758.

## Query-expansion experiment: finished (2026-10-31)
`eval/expand_eval.py` now runs from cached expansions (no LLM). Best config: **expand_vec w=1 + rerank**
strict R@1 .654, R@5 .904, R@10 .942, MRR .767, nDCG .796, variant acc 1.0 | lenient R@5 .942, MRR .836, nDCG .840.
vs baseline+rerank: strict MRR .730 -> .767, R@5 .846 -> .904; lenient MRR .832 -> .836 (tie). Weights .5 and 2 are both worse. Lexical-side expansion adds little.
Caveats: 52 questions, gains are small/within noise; unanswerable AUC is .779 with expansion alone but ~.50 once reranked (rerank hurts abstention signal).
**Adopted**: `server.py` `_Expansion` (lazy Gemma on Vulkan0:8096, unloads after 300 s idle, per-query cache, falls back to plain search on failure). Env: `DOCSEARCH_EXPAND=off`, `DOCSEARCH_EXPAND_IDLE`, `DOCSEARCH_EXPAND_DEVICE/PORT`. Measured via MCP call: cold 6.7 s (loads 3 servers), warm uncached ~2.5 s.

## Corpus additions (2026-10-31)
Shallow clones (`--shallow-since=2026-01-01`) of MicrosoftDocs `azure-aks-docs`, `azure-monitor-docs`, `azure-compute-docs`, `azure-docs-powershell` (+ `aks-samples`), registered in `repos.toml`. PowerShell indexes only `azps-16.4.0` (new `restrict = true` option limits a repo to its `docs_root`; the cmdlet reference keeps older `azps-*` versions side by side) at weight 0.5; **when a newer azps-X folder appears, update `docs_root`**. Added 86,080 chunks (index 181,432 -> 267,518; 1.5 GB). Because these clones are shallow, the first `docsearch update` falls back to a full reprocess for them. Embedding ran at only 22-28 chunks/s (slower than the earlier 40-50).
Re-eval on the bigger index (server config): strict R@5 .904 -> .885, MRR .767 -> .753 (about one question; new pages compete with the gold ones), lenient unchanged (R@5 .942, MRR .838), canaries ok. Learn MCP URLs present in the index: 442/580.

## Next steps, in priority order
1. ~~Re-run canaries~~ done: all 15 canary ids stay in the top 5 under both the default and the server config (rerank + expansion). `canary.py` keeps testing the default config on purpose (index integrity, no extra GPU servers); no change needed.
2. Real failures (investigated 2026-10-31; only q008, q013, q022 miss the top 5 under the server config):
   - q022 blob diagnostic setting/PowerShell: **corpus-limited** (still true: that include is not among the 9 reconstructed). The gold page `monitor-blob-storage.md` gets its diagnostic-setting text from an unresolved private include (`reusable-content`), so it is not in the index. Not fixable by retrieval; resolves only if that repo becomes available.
   - q013 read-only RBAC: gold page never says "read-only" (answer is the Reader role). v1 expansion misses "Reader"; vector rank of gold 324.
   - q008 VM backup intro: gold is 5th in the expanded vector list but drops out in fusion; many backup quickstarts outrank the overview page. Reranking deeper does NOT help (top 10/15/20/30: R@5 flat .904, MRR .767-.779, unanswerable AUC falls .50 -> .40), so keep rerank_top=10.
   - Tried a second expansion prompt (article title + official names; `eval/expand_prompt_v2.py`, cache `eval/results/expansions_v2.json`): strict MRR .767 -> .781 but R@5 .904 -> .885; lenient equal. A wash within noise, NOT adopted. It does produce "Reader" for q013.
3. Stronger embedding model: slice test done (`eval/embed_slice.py`; 7,058-chunk pool = nomic/BM25 top-40 per question + gold pages + 2,500 random; vector-only ranking, page level). nomic strict R@5 .808 MRR .703 / lenient .885 .762 | **bge-m3 Q8** strict .865 .727 / lenient .885 .784, 20 chunks/s (full re-embed ~2.5 h, 1024-d, +33% index size) | Qwen3-Embedding-0.6B Q8 strict .846 .623 / lenient .865 .668, 6 chunks/s (~8 h; weaker R@1, possibly last-token/EOS handling) - rejected. bge-m3 gain is ~3 questions at R@5 strict and flat lenient: within noise, and likely smaller after rerank + expansion. Not adopted yet; a full-pipeline test would need a full re-embed.
4. Overlap lexical and vector stages in threads (~200 ms saving), if latency matters.
5. ~~Clone missing sample/include repos~~ done 2026-10-31: 106 dependent repos shallow-cloned as siblings of the corpus (from `dependent_repositories` in azure-docs/azure-dev-docs publish configs); only `reusable-content`, `azure-dev-docs-pr`, `azure-policy-autogen-docs` are private. Rebuild reused 178,962 vectors, embedded 2,470; snippet-unresolved pages 517 -> 58, include-unresolved still 1,032 (reusable-content). Index now 181,432 chunks (`index-20261031-125929721.db`).
6. ~~Register the MCP server~~ done 2026-11-01 (user scope; takes effect in new Claude Code sessions). Nightly timer installed 2026-11-01 (user units in ~/.config/systemd/user, 03:30 +-10 min, `Persistent=true`; log `data/nightly.log`; `systemctl --user list-timers docsearch-update.timer`). Needs user lingering (`loginctl enable-linger vivo`) to fire when nobody is logged in.

## Known limits
Eval set is small (4 multi-page, 6 variant questions) and corpus-bound; half of Learn MCP's results are outside this checkout, so its MRR is understated.
Cosmos DB and Key Vault docs are still not in the corpus (their public repos were not found under the names tried: MicrosoftDocs/azure-databases-docs, azure-security-docs). Also absent: dotnet/api, javascript/api, Q&A (`answers/`), minecraft, Bicep registry READMEs.

---
# Move to the new server (2026-10-31) — READ THIS FIRST on the new machine

Old: RX 6600 8 GB (Vulkan), ~224 GB/s. New: **RX 7900 XTX 24 GB (gfx1100)**, ~960 GB/s, 64 GB RAM, Ryzen 7 5700X, NVMe. Expect ~3-4x faster GPU inference, and all models fit in VRAM at once.

## State at the move
- bge-m3 full-corpus experiment was **stopped** at 7,500/267,518 chunks (5.8-6.1 chunks/s on the RX 6600 = ~12 h; the slice test had suggested 20/s, cause of the gap unknown). `data/exp-bge-m3.db` is a useless partial copy: delete it, do not transfer it.
- `eval/bge_full.py check|embed` (builds `data/exp-bge-m3.db` from current.db, 1024-d, cls pooling, no prefixes, port 8095, resumable) and `eval/bge_eval.py` (nomic vs bge-m3, five fixed configs, strict+lenient, canaries, per-question rank changes) are written; `check` passed (cosine 0.9999 vs slice), `bge_eval.py` has never been run.
- Pre-registered adoption bar for bge-m3: >= 2 more questions at R@5 under the SERVER config (or clearly higher MRR) on BOTH strict and lenient, no AUC/canary regression. Do not retune weights for the new model.
- A stale nomic llama-server (port 8099) was left from the last build; irrelevant on the new box.

## Hardware-driven re-review of decisions
1. **Embedding model: re-run the bge-m3 full test first** (~1-3 h expected instead of 12 h). Q8 or even F16 is fine in 24 GB. Also worth retesting Qwen3-Embedding (0.6B had weak R@1 and 6 chunks/s; 4B/8B now fit; check last-token pooling/EOS handling, which may have caused the weak R@1). Rejection reasons were speed, not only quality.
2. **Reranker**: bge-reranker-v2-m3 Q8 top-10 stays the default. Qwen3-Reranker-4B was rejected for "no better, 5-8 s": retest (latency ~1-2 s now) and try the 8B. Deeper rerank (top 20-30) did not help quality, so don't just raise rerank_top.
3. **Query expansion LLM** (Gemma, lazily loaded, unloaded after 300 s idle): with 24 GB keep embed + reranker + LLM **resident** (set `DOCSEARCH_EXPAND_IDLE` high / disable unload) so cold start (6.7 s) disappears; a larger LLM for expansion is now possible but must beat the current set on the eval before adoption. Expansion prompt v2 was a wash.
4. **Contextual retrieval over the whole corpus** was rejected at ~92 h (Gemma, RX 6600). At ~4x it is still ~25 h: only revisit on a subset or after the embedding decision; not a first priority.
5. **Latency**: priority remains precision over latency. Warm ~1.8 s should drop to well under 1 s; overlapping lexical/vector threads (~200 ms) becomes the remaining cheap win.
6. **Llama.cpp backend**: `--device Vulkan0` is hardcoded in several places (embed.py, rerank.py, expand.py defaults; env `DOCSEARCH_EMBED_DEVICE/PORT`, `DOCSEARCH_EXPAND_DEVICE/PORT`). On the new box check `llama-server --list-devices`; try a ROCm/HIP build (gfx1100) vs Vulkan and benchmark both. The "server slows 2x with uptime; restart every 15k chunks" gotcha was seen on RX 6600/Vulkan: re-measure before keeping it (it is cheap to keep).
7. **Biggest remaining limit is not compute but the eval set** (52 questions, 1 question = 0.019 R@5, nearly every result so far is within noise). Before more model swaps, grow `eval/questions.jsonl` (and judgments) substantially; compute is now cheap enough to run many comparisons.
8. Unchanged: SQLite FTS5 + sqlite-vec design, chunker, RRF/boosts, prose-only v1, MCP tools, nightly update design.

## Porting checklist
- Paths: project assumed at `/home/vivo/repo/Microsoft` with corpus repos as siblings (106 shallow clones + the 14 indexed repos; `repos.toml`). Easiest: rsync the whole `Microsoft/` tree except `LLM/docsearch/data/exp-bge-m3.db`, `.venv`, and old `index-*.db` (keep `current.db` target only), then `uv sync`.
- Models: nomic GGUF came from LM Studio's bundled dir (`BUNDLED_NOMIC` in embed.py): copy the GGUF or change the path. HF cache models needed: bge-m3 Q8 (ggml-org), bge-reranker-v2-m3 Q8 (gpustack), the Gemma GGUF (see `expand.py` GEMMA).
- `llama-server` must be on PATH with GPU support. `uv run pytest -q` (74 tests) after porting.
- If the index schema/vectors are kept (nomic 768-d), `data/current.db` can be copied as is (1.5 GB). If bge-m3 wins, the whole index must be re-embedded and `store.DIMS`, `embed.py` (MODEL_ID, pooling cls, no DOC/QUERY prefix), server `_Embeddings` and canary.py all need the new model; content_hash includes MODEL_ID so the nightly update re-embeds everything.
- MCP server registered and nightly timer installed (see above).
- Claude memory: copy `handoff-memory/*` into `~/.claude/projects/<mangled-project-path>/memory/` on the new machine (see handoff-memory/README.md).

## Running long jobs (2026-10-31)
Use `../scope/scoperun.sh <slug> <log> <cmd...>` (systemd user scope `ds-<slug>`) and `scopestatus/scopewait/scopestop/scopels.sh`
from `LLM/scope/` (see its README). Never `pkill`/`pgrep -f`: they match their own command line.
