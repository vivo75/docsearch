# docsearch — handoff (state as of 2026-11-03)

Implements `../option-2-local-hybrid-index.md`. Everything lives in this directory; `data/` (gitignored) holds the index.
Run tests: `uv run pytest -q` (94 pass). No background jobs are running; no llama-server is left running (verified 2026-11-03; re-verified after the OS upgrade 2026-11-04).
Live index: `data/current.db` -> `index-20261104-033951333.db` (as of 2026-11-04; 2026-11-03 figures: 37,166 docs / 300,493 chunks, 17 repos, Qwen3-Embedding-4B, vecmat `.npy` present).

## Review of 2026-11-04 (read first)
Three read-only reviews (code, evaluation method, algorithms) led to: (1) robustness fixes, commits `9528530` and earlier: models run outside the Searcher lock, `_Embeddings`/`_Reranking` restart after a backend crash (canary now uses port 8104), failed index reopen keeps the old one, ordered filtered BM25, `build.publish_index` (vecmat cache + swap) used by build/update/migrate, `store.swap` never prunes the live index and drops stale `.partial`, cross-repo dependents after a full reprocess, 5xx retry in the embedder, bare "node" no longer infers JavaScript, `server.make_searcher` shared by CLI and MCP (`docsearch search` now expands queries like the server).
(2) Reranker text length 1200 -> 3000 chars (eval B9, gate PASS on test). (3) `search_docs(queries=[...])` (B10, implemented, no measured gain; optional). (4) `compare.py --gate/--override` makes the adoption rule mechanical; overrides are logged in `eval/decisions.jsonl`.
Not done / ideas left: group variant duplicates before the rerank (M6), infer variants from the user query only (not the Gemma expansion), section-level score aggregation, re-ablate Gemma expansion on Qwen3, convex-combination fusion, fp16 vectors; a real-query eval set (needs human judgments); re-pool lenient judgments on the live index; unanswerable labels for Cosmos/Key Vault (n0555). The nightly's first `--canary` run with the new reranker length is the remaining check of adoption rule 4.

## OS upgrade check (2026-11-04) — read if search ever returns "semantic search unavailable"
After the deep OS upgrade (Fedora 45, kernel 7.2, system Python 3.15): `.venv` is on uv's Python 3.14.7, 94 tests pass, MCP (stdio + HTTP unit) and the nightly timer are fine; no code changes were needed.
What broke was **llama.cpp**, not docsearch: the old `/usr/local` build failed on `librccl.so.1` (fixed with `sudo dnf install rccl`), then a rebuilt Vulkan lib compiled with `GGML_VULKAN_CHECK_RESULTS`/validation layers segfaulted at startup (exit -11, hundreds of `avg_err=` lines).
Now: **static build** of `/usr/local/bin/llama-server` (version 0.8.0-dev, build 12101, Vulkan, no debug flags; broken `libggml*.so` symlinks in `/usr/local/lib64` removed). Verified: embed server healthy, 2560-d, canaries OK, MCP `warnings: []`.
Warm latency via MCP (uncached query): **~0.9 s** (lexical 298, expand 154, vector 299, rerank 135 ms); repeated query (cache) ~0.5 s; cold first query ~14 s (loads the embed/rerank/expand servers).
Symptom check: `docsearch search "<q>"` printing `semantic search unavailable (RuntimeError)` / `reranker unavailable` = llama-server cannot start; try `llama-server --version`, then `ldd /usr/local/bin/llama-server | grep "not found"`, then start the embed server by hand and read its log.
The nightly was not re-run after the upgrade (last run 2026-11-04 03:39, before it); check `data/nightly.log` on 2026-11-05.

## Reconstructed includes (2026-11-01, extended 2026-11-03) — read before touching `reusable-content`
`/mnt/D500G/space/Microsoft/reusable-content/` and `.../azure-dev-docs-pr/` are **NOT the real repos**: stand-ins (25 files: 18 in reusable-content under `ce-skilling/azure/includes/` + `azure-cli/`, 7 in azure-dev-docs-pr under `articles/`) rebuilt from the
rendered Learn pages of the most-used unresolved includes (free-trial note, updated-for-az, both azure-cli-prepare-your-environment, AKS preview callout,
ARM and Bicep intros, cloud-shell-try-it, the terraform family: abstract, init, plan, plan-notes, apply-plan, plan-destroy, plus the 10 Azure Monitor
`horz-monitor-*` horizontals added 2026-11-03). Each file has `reconstructed: true` + source URLs in frontmatter (stripped at index time, so the
index text is unmarked); each directory has `RECONSTRUCTED.md` and `manifest.json`. They are not git repos and not in `repos.toml`. Known weak spots: link URLs lost,
markup/code fences partly inferred. Skipped on purpose: `horz-monitor-ref-*` tables, `horz-monitor-insights*`, legal disclaimers, bastion-pricing, ephemeral-ip-note, azure-disk-encryption-retirement (`horz-monitor-ref-metrics-tableheader.md`: header boundary unclear). To undo: delete both directories and run `docsearch build`
(`docsearch update` would not notice the removal: it only heals newly resolvable includes, not vanished ones). If the real repos are ever cloned, replace the directories and `docsearch build`.
- `docsearch update` now **heals** pages: `_heal_unresolved` (update.py) re-resolves every `*_unresolved` page and reprocesses those that gained a dependency not in `deps`
  (no git change needed; ~1,700 page reads). First run: 977 pages, 12,340 chunks, 1,489 embedded; index `index-20261101-195217309.db` (superseded; `pre` in compare.py).
  Terraform batch: live index at the time `index-20261101-210737332.db` (`h1` in compare.py = the one before); qinc R@5 .417 -> .667 on 72 questions. Monitor batch (2026-11-03):
  35 pages / 597 chunks healed, live index `index-20261103-012303802.db` (`prem` in compare.py, kept as `data/exp-qwen3-premon.db`). Nightly 2026-11-03 pulled upstream and healed
  547 pages / 7,245 chunks; live index `index-20261103-033921362.db`. qset2 test identical before/after the monitor heal (strict R@5 .869, MRR .726; lenient .947/.882), no regression.
- Results: no change on qset2 (test/dev), large gain on the include-targeted sets qinc (R@5 .167 -> .604, 48 q) and qmon (R@5 .067 -> .700, 60 q); details in eval/README.md ("qinc", "qmon").
- Method (reusable for more includes, ~399 distinct unresolved includes, the 10 used cover ~1,280 of 1,752 occurrences): list unresolved includes with their pages (IncludeResolver on flagged docs),
  fetch 3 rendered pages per include at 1 request / 0.8 s, give source+rendered text to a Haiku agent to extract the text at the marker, check the 3 extractions agree. Avoid tables/tab-heavy includes.
- Next: remaining includes are tables/insights/disclaimers (`horz-monitor-ref-*`, `horz-monitor-insights*`, legal, bastion-pricing, ephemeral-ip-note, azure-disk-encryption-retirement); then re-run `compare.py` on qset2 + qinc + qmon.

## What exists and works
| area | where |
|---|---|
| Parsing, includes, snippets, variants, URLs, chunking | `src/docsearch/{frontmatter,includes,snippets,variants,urls,normalize,chunker,pipeline}.py` |
| Full build (parallel parse, resumable embed, health checks, atomic swap) | `docsearch build` (`build.py`, `store.py`, `embed.py`) |
| Published index | `data/current.db` -> `index-20261103-033921362.db` (37,166 docs / 300,493 chunks, 17 repos; Qwen3-Embedding-4B; vecmat `.npy` present) |
| Retrieval | `search.py`: BM25 + identifier FTS + sqlite-vec (or exact in-memory `vecmat` when its `.npy` is present), RRF, boosts, variant grouping, optional rerank + query expansion; `confidence` + `rerank_max` + `toc` on hits |
| MCP server | `docsearch serve` (`server.py`): search_docs, expand, read_doc, outline_doc, browse, grep_docs. Registered in Claude Code (user scope, 2026-11-01); HTTP unit `deploy/docsearch-mcp.service` active on `100.100.121.1:8765` (verified 2026-11-03) |
| Nightly incremental update | `docsearch update [--pull] [--dry-run] [--canary]`, `docsearch verify`, `docsearch changes`; `deploy/nightly.sh` + systemd units **installed and active** (timer fires 03:30 +10min, `Persistent=true`; log `data/nightly.log`, reports `data/reports/`) |
| Eval | `eval/` (qset2: 626 q, qset3: 95 q, qinc: 72 q, qmon: 60 q, v1: 58 q; README with results/caveats; adoption rule in README "Adoption rule"; scripts `compare.py`, `run_eval.py`, `rerank_eval.py`, `expand_eval.py`) |

Registered 2026-11-01 with `claude mcp add --scope user docsearch -- /mnt/D500G/space/Microsoft/LLM/docsearch/.venv/bin/docsearch serve` (verified connected 2026-11-03).
Nightly timer: installed 2026-11-01 from `deploy/` (see header of `deploy/docsearch-update.service`); verified active 2026-11-03 (last run 03:38, next 2026-11-04; `loginctl show-user vivo` -> `Linger=yes`).

## Decisions taken (updated 2026-11-03)
- Embeddings: **Qwen3-Embedding-4B Q8_0 in production since 2026-11-02** (2560-d, last-token pooling, `<|endoftext|>` + query prefix; `embed.py` `MODEL_ID`, `prod_server`/`prod_embedder`; `store.DIMS=2560`). Nomic (768-d) kept only in `eval/legacy.py` + `data/exp-nomic-baseline.db`. Restart-the-server-every-15k-chunks gotcha was seen on RX 6600/Vulkan; re-measure before relying on it.
- Reranker: **bge-reranker-v2-m3 Q8**, top 10, fused with original rank at equal weight (`SERVER_CONFIG` in `server.py`), **3,000 chars per chunk since 2026-11-04 (B9; was 1,200)**. Disable with `DOCSEARCH_RERANK=off`.
- Variant boost: **`variant_boost=0.6` in `SERVER_CONFIG`** (adopted 2026-11-03, eval B8): tool mentions in the query boost matching tab/pivot chunks; `_collapse` prefers them as the shown snippet. Test: var_acc strict .750->.857, lenient .750->.821, MRR/R@5 neutral (rule 1 unmet, user override), canaries pass.
- Rejected: Qwen3-Reranker-4B/8B + Prism-Qwen3.5-4B (B1: no significant strict gain, 3-5 s vs 1.3 s; Prism lenient MRR +.017 but strict ns — not adopted; Prism abstention AUC .964 worth revisiting), jina-reranker-v3 (returns 0 via llama.cpp), bge-m3 as embedding (twice rejected: v1 slice + full-corpus B7/qset2 test), int8/binary vectors (no speedup / lost precision), whole-corpus contextual retrieval with Gemma (~92 h on RX 6600).
- Priority from the user: precision and meaningful results over latency. Current warm latency **~0.9 s via MCP** (re-measured 2026-11-04 after the OS upgrade; 2026-11-03 `queries.jsonl`: lexical ~230 ms, expand ~300 ms, vector ~310 ms via vecmat, rerank ~100-140 ms).

## Eval numbers — v1 set (historical; superseded by qset2/qset3/qinc/qmon in `eval/README.md`)
v1 (52 answerable; strict gold / lenient = with pooled judgments): default hybrid R@5 .846/.923, MRR .692/.800 | + rerank R@1 .635/.750, MRR .730-.738/.830 | Learn MCP R@5 .769 | grep proxy .385.
Query expansion with Gemma (strict, v1-era): vector-side expansion **R@5 .904, R@10 .942, variant acc 1.0, unanswerable AUC .779** (best recall gain at the time);
both sides + rerank MRR .758.

## Query-expansion experiment: finished (2026-10-31); model is now `gemma-4-E4B-it` (2026-11-02+)
`eval/expand_eval.py` now runs from cached expansions (no LLM). Best config: **expand_vec w=1 + rerank** (v1 numbers:
strict R@1 .654, R@5 .904, R@10 .942, MRR .767, nDCG .796, variant acc 1.0 | lenient R@5 .942, MRR .836, nDCG .840).
vs baseline+rerank: strict MRR .730 -> .767, R@5 .846 -> .904; lenient MRR .832 -> .836 (tie). Weights .5 and 2 are both worse. Lexical-side expansion adds little.
Caveats: 52 questions, gains are small/within noise; unanswerable AUC is .779 with expansion alone but ~.50 once reranked (rerank hurts abstention signal).
**Adopted**: `server.py` `_Expansion` (lazy `gemma-4-E4B-it-Q4_K_M` on Vulkan0:8096, unloads after 300 s idle, per-query cache, falls back to plain search on failure). Env: `DOCSEARCH_EXPAND=off`, `DOCSEARCH_EXPAND_IDLE`, `DOCSEARCH_EXPAND_DEVICE/PORT`. Measured via MCP call: cold 6.7 s (loads 3 servers), warm uncached ~2.5 s (pre-vecmat).

## Corpus additions (2026-10-31, extended 2026-11-01; historical numbers)
Shallow clones (`--shallow-since=2026-01-01`) of MicrosoftDocs `azure-aks-docs`, `azure-monitor-docs`, `azure-compute-docs`, `azure-docs-powershell` (+ `aks-samples`), registered in `repos.toml`. PowerShell indexes only `azps-16.5.0` (new `restrict = true` option limits a repo to its `docs_root`; the cmdlet reference keeps older `azps-*` versions side by side) at weight 0.5; **when a newer azps-X folder appears, update `docs_root`** (bumped 16.4.0 -> 16.5.0 on 2026-11-04; meta-head deletion forces the full re-ingest, vectors reused by content hash, only changed cmdlets re-embedded). Added 86,080 chunks (index 181,432 -> 267,518 at the time). Because these clones are shallow, the first `docsearch update` falls back to a full reprocess for them. Embedding ran at only 22-28 chunks/s on the old box (slower than the earlier 40-50).
Re-eval on the bigger index (server config, v1-era): strict R@5 .904 -> .885, MRR .767 -> .753 (about one question; new pages compete with the gold ones), lenient unchanged (R@5 .942, MRR .838), canaries ok. Learn MCP URLs present in the index: 442/580.
Superseded 2026-11-01: corpus2 added Azure CLI docs/reference + support articles (17 repos, 299,349 chunks at the time); 2026-11-03 live index is 300,493 chunks. See `eval/README.md` qset3 (coverage gain) and the Qwen3 promotion (B7).

## Next steps, in priority order
1. ~~Re-run canaries~~ done (v1-era: all 15 canary ids in the top 5 under default and server config). `src/docsearch/canary.py` (run via `docsearch update --canary`, lenient gold, top-5) keeps testing integrity; nightly runs it before every publish.
2. Real failures (investigated 2026-10-31 on v1/nomic; **re-checked 2026-11-03 on the live Qwen3 index, server config: all three still miss the top 5** — q008 rank 11, q013 absent, q022 rank 10):
   - q022 blob diagnostic setting/PowerShell: **corpus-limited at the time** (that include was not among the reconstructed sets). The gold page `monitor-blob-storage.md` gets its diagnostic-setting text from an unresolved private include (`reusable-content`), so it was not in the index. Not fixable by retrieval; resolves only if that repo becomes available. Re-check 2026-11-03 (live Qwen3): gold rank 10, hit carries no powershell variant; top-1 is now the generic `azure-monitor/.../diagnostic-settings.md` (has a powershell variant) — arguably the better answer but not lenient gold. Partially mitigated, still misses.
   Fixed 2026-11-03 as eval hygiene: the gold's PowerShell tab covers only metric reads; the generic page carries the canonical `New-AzDiagnosticSetting` procedure (cmdlet resource-agnostic) → added as lenient `also_ok` (`eval/judgments.json`). User review 2026-11-04: the cmdlet reference `azps-16.5.0/Az.Monitor/New-AzDiagnosticSetting.md` is the most suitable page (full syntax + examples) but ranks #35 (generic reference text, no blob-specific terms) → added as second `also_ok` (no metric change; lenient rank stays 1 via the how-to). Strict still misses by design (gold lacks the text); lenient now rank 1, variant_ok true. v1 lenient with both fixes (`results/20261103-180912-compare-v1-all.json`): R@5 .923->.962, MRR .838->.865, var_acc .833->1.000.
   - q013 read-only RBAC: gold page never says "read-only" (answer is the Reader role). v1 expansion misses "Reader"; vector rank of gold 324. Re-check 2026-11-03 (live Qwen3): gold absent from the rankings; all top-10 rerank scores low/negative (best 2.73, unrelated permissions page); expansion still has no "Reader". Confirmed, not a regression.
   Fixed 2026-11-03 as eval hygiene (retrieval cannot find terms that are not there): v2 expansion ("Reader", verified) still leaves gold outside top-12, and the gold page is a generic assign-any-role procedure. `tutorial-role-assignments-group-powershell.md` (already top-1; assigns Reader with `New-AzRoleAssignment`, subscription scope inherited by RGs) added as lenient `also_ok` (`eval/judgments.json`, single-reviewer — confirm with the judge). Strict still misses by design; lenient now rank 1.
   User review: `built-in-roles.md` (full catalog, Reader row with id `acdd72a7-...`) ranks #18/#21 and `built-in-roles/general.md` (Reader definition) #15/#16 — they give the *value* but not the *how*. Adopted multi-gold conceptual (q007 precedent): strict gold = [role-assignments-portal.md, built-in-roles/general.md]; strict rank 15, coverage 0/2; lenient rank 1 via tutorial. Record: `results/20261103-234250-compare-v1-all.json` (strict R@5 .885 MRR .755; lenient R@5 .962 MRR .862, var_acc 1.000).
   - q008 VM backup intro: gold is 5th in the expanded vector list but drops out in fusion; many backup quickstarts outrank the overview page. Reranking deeper does NOT help (top 10/15/20/30: R@5 flat .904, MRR .767-.779, unanswerable AUC falls .50 -> .40), so keep rerank_top=10. Re-check 2026-11-03 (live Qwen3): gold rank 11, top-10 all backup-VM siblings (top `backup-azure-vms-first-look-arm.md`, rerank 4.91). Confirmed retrieval ("wrong sibling"), not corpus.
   Closed 2026-11-03 as correctly-hard, no code change: isolating intent shows the ×1.12 how-to boost pushes gold below the rerank cutoff (14th vs 9th with intent off) AND the cross-encoder itself prefers specifics (gold 3.88 vs 4.4-4.9) AND the lexical verb/noun split ("back up" in how-to titles vs "backup" in the overview) favors how-tos. A blanket what→overview intent is ruled out by dev-wide data (what-questions are mostly how-to/troubleshooting: n0161, n0175, n0584, n0281...). No also_ok: the top how-tos answer only the "how" half, not "what gets backed up". Prototype case for section-level retrieval (miss analysis: 28% of misses).
   - Tried a second expansion prompt (article title + official names; `eval/expand_prompt_v2.py`, cache `eval/results/expansions_v2.json`): strict MRR .767 -> .781 but R@5 .904 -> .885; lenient equal. A wash within noise, NOT adopted. It does produce "Reader" for q013.
3. ~~Stronger embedding model~~ done 2026-11-02: Qwen3-Embedding-4B adopted (B7: qset2 test strict R@5 +.049, lenient +.035, MRR +.015/+.031, all CIs above 0 except strict MRR; qinc control ns; p50 1.3 -> 3.6 s pre-vecmat). Slice test that led there (`eval/embed_slice.py`; pool = nomic/BM25 top-8 per qset2 question + gold pages + 2,500 random; vector-only, page level): nomic strict R@1/R@5/MRR .548/.802/.662 | bge-m3 .592/.869/.712 | **Qwen3-4B .719/.940/.814** | Qwen3-8B .730/.947/.820. bge-m3 full-corpus test rejected twice (v1 run + qset2 test: strict +2 q at R@5 but lenient MRR -.025, variant acc 1.0 -> .833; fails the pre-registered bar). No further embedding work planned without a new eval set.
4. Overlap lexical and vector stages in threads (~200 ms saving), if latency matters. Less urgent now: vecmat brought warm p50 to ~1.0 s.
5. ~~Clone missing sample/include repos~~ done 2026-10-31: 106 dependent repos shallow-cloned as siblings of the corpus (from `dependent_repositories` in azure-docs/azure-dev-docs publish configs); only `reusable-content`, `azure-dev-docs-pr`, `azure-policy-autogen-docs` are private. Rebuild reused 178,962 vectors, embedded 2,470; snippet-unresolved pages 517 -> 58 (at the time). Index at the time 181,432 chunks (`index-20261031-125929721.db`, superseded).
6. ~~Register the MCP server~~ done 2026-11-01 (user scope) + HTTP unit 2026-11-02. Nightly timer active (user units in ~/.config/systemd/user, 03:30 +10 min, `Persistent=true`; log `data/nightly.log`, reports `data/reports/`; `systemctl --user list-timers docsearch-update.timer`). Linger on (`loginctl show-user vivo` -> `Linger=yes`, verified 2026-11-03).

## Known limits (updated 2026-11-03)
Eval is now qset2 (626 q, dev/test) + qset3 (95 q coverage) + qinc (72 q) + qmon (60 q) + v1 (58 q); the "52 questions / 0.019 per question" noise note applies to v1 only. qset2 test CIs are ~±0.025 MRR.
Cosmos DB and Key Vault docs are now in the corpus (2026-11-03, reconstructed from rendered Learn — see "Reconstructed service checkouts" below; 37,864 docs / 307,248 chunks, live index `index-20261104-004506113.db`).
Still absent: dotnet/api, javascript/api, Q&A (`answers/`), minecraft, Bicep registry READMEs. qset2 human review: 12 of 20 extra reviewer-named pages are not in the corpus (CLI reference, IoT Operations, support `troubleshoot/azure`, .NET API).

---
# Move to the new server (2026-10-31) — DONE, we are on the new machine (verified 2026-11-03)

Old: RX 6600 8 GB (Vulkan), ~224 GB/s. New: **RX 7900 XTX 24 GB (gfx1100)**, ~960 GB/s, 64 GB RAM (62 usable), 16 cores, NVMe (verified: `lspci` Navi 31, `free -g` 62 GB). All models fit in VRAM at once.

## State at the move (historical — resolved 2026-10-31/11-01 on the new box)
- bge-m3 full-corpus experiment: completed on the 7900 XTX in 83 min (53.6 chunks/s; the RX 6600 ran 6/s). `data/exp-bge-m3.db` (1.8 GB) is **kept** for re-tests (`compare.py` system `bge`), not deleted. `eval/bge_full.py check|embed` + `eval/bge_eval.py` both run; log `data/bge-eval.log`, summary `results/*-bge-vs-nomic.json`. Verdict: NOT adopted (strict +2 q at R@5 but MRR flat, lenient R@5 +1 q / MRR -.025 / variant acc 1.0 -> .833; fails the bar; qset2 test confirms: ΔMRR -.008/+.003, CIs include 0).
- Pre-registered adoption bar for bge-m3 superseded by the qset2 adoption rule (`eval/README.md` "Adoption rule", 2026-11-01): 95% CI of ΔMRR above 0 on both strict+lenient test, no R@5/nDCG regression, AUC drop ≤0.05, variant acc drop ≤0.05, canaries pass. Do not retune on the test set.
- No stale nomic llama-server remains (verified 2026-11-03: no `llama-server` process).

## Hardware-driven re-review of decisions (status 2026-11-03)
1. **Embedding model: DONE** — full Qwen3-Embedding test adopted 2026-11-02 (4B; 8B wins the slice by ~.01 but was not promoted). bge-m3 re-run completed and rejected.
2. **Reranker**: bge-reranker-v2-m3 Q8 top-10 stays the default. Qwen3-Reranker-4B/8B retested in B1 (latency still 3-5 s, no significant strict gain) + Prism-4B (lenient MRR +.017 but strict ns, 5.3 s). Deeper rerank (top 20-30) did not help quality, so don't just raise rerank_top. Prism worth revisiting only for abstention (test AUC .912 -> .964, n=25 unanswerable).
3. **Query expansion LLM** (`gemma-4-E4B-it`, lazily loaded, unloaded after 300 s idle): still unloads (see `server.py` `_Expansion`); keeping embed + reranker + LLM **resident** (`DOCSEARCH_EXPAND_IDLE` high) to kill the cold start was proposed but NOT done. A larger expansion LLM is possible but must beat the current set under the qset2 adoption rule. Expansion prompt v2 was a wash.
4. **Contextual retrieval over the whole corpus** was rejected at ~92 h (Gemma, RX 6600). At ~4x it is still ~25 h: only revisit on a subset or after the embedding decision; not a first priority. Still not revisited.
5. **Latency**: priority remains precision over latency. vecmat brought warm p50 to ~1.0 s (was ~1.8 s, then 3.6 s right after the Qwen3 promotion pre-vecmat); overlapping lexical/vector threads (~200 ms) is the remaining cheap win, still open.
6. **Llama.cpp backend**: `--device Vulkan0` is still the default (embed.py, rerank.py, expand.py; env `DOCSEARCH_EMBED_DEVICE/PORT`, `DOCSEARCH_EXPAND_DEVICE/PORT`). ROCm/HIP-vs-Vulkan benchmark proposed but NOT done. The "server slows 2x with uptime; restart every 15k chunks" gotcha was seen on RX 6600/Vulkan: not re-measured, still cheap to keep.
7. ~~**Eval set** (52 questions)~~ DONE: qset2 (626) + qset3 + qinc + qmon; test CIs ~±0.025 MRR.
8. Unchanged: SQLite FTS5 + sqlite-vec design, chunker, RRF/boosts, prose-only v1, MCP tools, nightly update design.

## Porting checklist (done 2026-10-31/11-01; kept for reference)
- Paths: project is at `/mnt/D500G/space/Microsoft/LLM/docsearch` with corpus repos as siblings (106 shallow clones + the 17 indexed repos; `repos.toml`).
- Models (in HF cache, verified 2026-11-03): bge-reranker-v2-m3 Q8 (gpustack), bge-m3 Q8, `gemma-4-E4B-it-Q4_K_M` (expansion), `gemma-4-26B-A4B` (judging), Qwen3-Embedding 0.6/4/8B, Qwen3.8-27B (summaries), `prism4b/` local reranker in `data/models/`. The old `BUNDLED_NOMIC` path is gone; nomic kept only for eval.
- `llama-server` on PATH with GPU support. `uv run pytest -q` (94 tests) after porting.
- If the index schema/vectors are kept (Qwen3-Embedding-4B 2560-d), `data/current.db` can be copied as is (3.8 GB + 3.1 GB `.npy`). content_hash includes MODEL_ID so the nightly update re-embeds everything after a model change.
- MCP server registered and nightly timer installed and active (see above; verified 2026-11-03).
- Claude memory: copy `handoff-memory/*` into `~/.claude/projects/<mangled-project-path>/memory/` on the new machine (see handoff-memory/README.md).

## Running long jobs (2026-10-31)
Use `../scope/scoperun.sh <slug> <log> <cmd...>` (systemd user scope `ds-<slug>`) and `scopestatus/scopewait/scopestop/scopels.sh`
from `LLM/scope/` (see its README). Never `pkill`/`pgrep -f`: they match their own command line.

## MCP over the network (2026-11-02)
`docsearch serve --http --host <addr> --port 8765` serves streamable HTTP at `http://<addr>:8765/mcp` (default stdio unchanged). **No authentication, no Host/DNS-rebinding check, no firewall**:
by decision of the user the network is fully trusted. Intended address: the `wg_k8s` interface, 100.100.121.1 (`ip -br addr show wg_k8s`). Tested with the `mcp` client (6 tools, `search_docs` answers).
`deploy/docsearch-mcp.service` is a user unit for it, installed by the user: `cp deploy/docsearch-mcp.service ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now docsearch-mcp`.
Client: `claude mcp add --transport http docsearch http://100.100.121.1:8765/mcp`. Linger is on (`Linger=yes`, verified 2026-11-03), and `docsearch-mcp` is active.

## Embedding model: Qwen3-Embedding-4B (2026-11-02, live; verified 2026-11-03)
Production vectors are Qwen3-Embedding-4B Q8_0 (2560-d, last-token pooling, query instruction prefix, `<|endoftext|>` on documents and queries); see `embed.py`
(`MODEL_ID`, `prod_server`, `prod_embedder`) and `eval/README.md` B7. `store.DIMS=2560`. Query/build servers use ports 8102/8103 (HF cache needs `Qwen/Qwen3-Embedding-4B-GGUF`).
Live index `index-20261103-033921362.db`: 300,493 chunks, model `Qwen3-Embedding-4B-Q8_0`. No stale nomic server remains. Nightly update re-embeds only changed chunks (hash includes MODEL_ID).
Rollback: `data/exp-nomic-baseline.db` is the last nomic index; point `current.db` at it AND revert embed.py/store.py to the commit before this one. `calibration.json` refitted on the Qwen index 2026-11-03 (bge-v2-m3-q8: a=0.769, b=0.553; n=566+58).

## In-memory vector search (`vecmat`, merged to `main` 2026-11-02)
`src/docsearch/vecmat.py`: per index, `index-STAMP.db.vec.npy` (L2-normalised float32, ~3.1 GB) + `.vec.rids.npy`. `Searcher._vector` uses it (mmap, exact cosine; measured ~300 ms warm via MCP 2026-11-03)
instead of sqlite-vec (~1.6 s) when present and consistent; otherwise (missing, wrong row count, `DOCSEARCH_VECMAT=off`) it silently falls back to sqlite-vec.
Built by `docsearch update` before the swap (failure only logs a warning), by `docsearch vecmat` (≈7 min on the full index), and pruned with the index in `store.swap`.
Adds ~3 GB of page cache/RAM per live index and ~3 GB of disk per kept index (3 `.npy` pairs kept: live + 2 predecessors). All three live-kept indexes have their `.npy` (verified 2026-11-03).

## Reconstructed service checkouts (2026-11-03): Cosmos DB + Key Vault
No public mirror exists for `MicrosoftDocs/nosql-docs-pr` (Cosmos DB, depot `Learn.azure-nosql`) or
`MicrosoftDocs/azure-security-docs-pr` (Key Vault, depot `Learn.azure-security`) under any name
(all API probes 404; only the private `-pr` repos exist, proven by Learn `original_content_git_url` meta).
`eval/crawl_learn.py` rebuilds them from rendered Learn markdown (`?accept=text/markdown`, 1 req/0.8s):
426 Cosmos + 205 Key Vault TOC nodes → 607 pages, 0 skipped. Frontmatter carries ms.service/topic/date,
source_path (exact repo layout), monikers; includes arrive expanded; zone pivots survive (`:::: zone` intact);
`ms.date` truncated to YYYY-MM-DD and the ` | Microsoft Learn` title suffix stripped at write time.
TOC.yml files are generated from the area toc.json files so `browse` works. Directories `nosql-docs/`,
`azure-security-docs/` (sibling layout like the other checkouts; `RECONSTRUCTED.md` + manifest + `.gitignore`
for the root meta files); `git init` + commit so `docsearch update` treats them as normal checkouts.
`repos.toml`: `nosql-docs` (docs_root `azure/cosmos-db`, url_base `.../azure/cosmos-db`) and
`azure-security-docs` (docs_root `articles/key-vault`, url_base `.../azure/key-vault`), both weight 1.0.
Live index `index-20261103-223408144.db` (after the manual nightly-equivalent run 22:33): 37,764 docs / 306,623 chunks
(581 crawled docs: 399 cosmos + 182 KV).
Spot checks pass: KV general queries hit `azure-security-docs` with correct Learn URLs; Cosmos RBAC query
hits `nosql-docs/.../how-to-connect-role-based-access-control` with all four tool variants accumulated.
Canaries pass on every publish.
- Gotchas found and fixed: (1) `RECONSTRUCTED.md` at checkout root got indexed until `restrict = true` was set
  (root files are out of scope only with restrict); (2) `update` is blind to config-only changes (restrict flip
  alone reprocesses nothing) and `removed` also honors `in_scope`, so dropping the stray doc needed
  restrict=false + meta-head rewind to the pre-deletion commit; (3) `git add -A` + root meta files: solved with
  committed `.gitignore`. Future work: hash repos.toml into the update plan so config changes take effect.
- Refresh: re-run `crawl_learn.py` (idempotent, skips unchanged) + commit, then the normal nightly update picks
  up diffs. External traffic is spread over the week: pages are sharded by `sha1(slug) mod 7` and `--shard auto`
  (ISO weekday) fetches one seventh per day (~90 pages, ~2 min); every run still walks all TOCs (cheap) so
  upstream deletions are picked up daily without downloads. New pages fall into a shard by hash automatically.
- Robustness fixes 2026-11-04 (from a real incident: the first sharded run pruned all TOC.yml to its seventh
  because the slug map was empty, and rewrote ~96 files on every run): (1) TOC generation uses the full known
  page set, never just the fetched shard; (2) slug→path map persisted in `manifest.json` (untracked via
  `.gitignore`); (3) upstream line endings vary per request (`\r`, `\r\n`, mixed) — full `\r` normalization
  before parsing, byte-exact comparison via `read_bytes` (text-mode universal-newline translation masked the
  diffs and defeated the skip), datetime-aware `ms.date` pinning to YYYY-MM-DD; (4) `.yml` FAQ sources
  (12: 10 cosmos + 2 KV, body already markdown) saved as `.md`, with old-path cleanup on rel change;
  (5) `manifest.json` untracked (`git rm --cached`) to keep commits to content. Verified: full re-crawl,
  then a sharded re-run reports "no changes" with a clean tree.
- Eval: qset2 no-harm run (`results/20261103-201926-compare-qset2-test.json`): strict R@5 .862->.862 MRR .723->.718,
  lenient R@5 .951->.943 MRR .883->.876, var_acc .857/.857 + .821->.857, AUC .92->.917 (paired: 1 strict loss + 1 gain,
  2 lenient losses incl. n0158 now competing with relevant new KV pages; within noise). Coverage question set qset4
  (109 q: 59 cosmos + 50 KV; `eval/README.md` qset4; `results/20261103-223313-compare-qset4-all.json`): lenient
  R@5 .486->.982, MRR .403->.934, nDCG .242->.755 (all CIs far above 0); strict live R@5 .917 MRR .803 (prem 0.000
  by construction). 62/109 already had an old-corpus grade-2 page; 47 need the additions.

## Azure Monitor includes recovered (2026-11-03; verified in the live index)
10 more stand-in files in `reusable-content/.../azure-monitor/horizontals/` (listed in its `RECONSTRUCTED.md`/`manifest.json`; generic text from the rendered App Service monitoring page). Still unresolved and
skipped on purpose: `horz-monitor-ref-*` (tables), `horz-monitor-insights*`, the legal disclaimers, bastion-pricing, ephemeral-ip-note, azure-disk-encryption-retirement. qmon results: eval/README.md.
Healed 35 pages / 597 chunks (`index-20261103-012303802.db`); nightly 2026-11-03 added 547 pages / 7,245 chunks on top (live `index-20261103-033921362.db`).

## Change reports (2026-11-03; new since the last handoff)
`docsearch changes [--summ] [--lang] [--out]` (`src/docsearch/changes.py`): groups the last update's touched files by documentation area (git diff old→new HEADs per repo) with commit titles; `--summ` adds 1-2-sentence LLM summaries per area.
Summaries default to Qwen3.8-27B (`unsloth/Qwen3.8-27B-GGUF` Q4_K_M, 36 layers on GPU ≈ 10 GB VRAM alongside the resident MCP models, 2 h budget) with `gemma-4-E4B-it` fallback; nightly writes `data/reports/changes-<index>.md` (see `deploy/nightly.sh`). First report: `data/reports/changes-index-20261103-033921362.db.md`.
