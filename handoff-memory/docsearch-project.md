---
name: docsearch-project
description: State and decisions for the Option-2 local hybrid docs index (LLM/docsearch) over the Microsoft docs corpus
metadata:
  type: project
---

Implementing option-2 from /home/vivo/repo/Microsoft/LLM/option-2-local-hybrid-index.md as a uv/Python 3.14 package at /home/vivo/repo/Microsoft/LLM/docsearch (repos.toml = corpus config). Phase 0 gate skipped by user choice; eval harness comes after the indexer.

Decisions: embeddings via llama-server (Vulkan, RX 6600, `--device Vulkan0`) with LM Studio's bundled nomic-embed-text-v1.5 GGUF (768-d, ~16k tok/s, prefixes search_document:/search_query:). Index = SQLite FTS5 + sqlite-vec. Prose only for v1.

Done: steps 1-6. Full index published at LLM/docsearch/data/current.db (180,515 chunks, 18,562 docs, 1 GB, toc table + ISO dates via `docsearch migrate`). Retrieval = src/docsearch/search.py (BM25 + identifier FTS + sqlite-vec, RRF, boosts, variant grouping); MCP server = `docsearch serve` (mcp 2.x MCPServer, 6 read-only tools: search_docs/expand/read_doc/outline_doc/browse/grep_docs). Step 7 done: eval harness + 58-question set in LLM/docsearch/eval/ (README has results and caveats): default hybrid R@5 0.846 / MRR 0.692 strict; Learn MCP R@5 0.769, grep proxy 0.385; ablations show a plateau (all within noise). Next: fix real failures (e.g. read-only RBAC question, diagnostic-setting question), reranker/contextual-retrieval experiments (need model download or local gemma LLM), latency, nightly incremental update. Old next-list: step 7 eval harness + tuning (latency ~0.7-1.3 s/query is above the design's 200 ms target; ranking untuned), incremental nightly update, then maybe register the server in Claude Code.

**Why:** `reusable-content` repo is private (clone fails) -> ~2,080 includes unresolved; ~2,250 snippet refs point at uncloned sample repos (azure-storage-snippets etc.). Known/accepted; flagged per page, not a build failure.
**How to apply:** don't re-try cloning reusable-content; token counter in chunker.py is an estimate, calibrate vs llama-server /tokenize in step 5.

**Gotcha:** a long-running llama-server slows ~2x under sustained embedding load; build.py restarts it every 15k chunks (resume with `docsearch build --resume data/<file>.partial`). Query-time server uses port 8098 (DOCSEARCH_EMBED_DEVICE/PORT env vars).

**Session paused 2026-10-31.** Full handoff with decisions, numbers, unfinished experiment and ordered next steps: `LLM/docsearch/HANDOFF.md` (read it first). Nothing is running; live index is data/current.db. Reranker chosen: bge-reranker-v2-m3 Q8 top-10 rrf (in server SERVER_CONFIG). Unfinished: Gemma query-expansion experiment (vector-side expansion was the best recall gain: R@5 .846->.904) — still to test expand_vec + rerank and lenient pass. User priority: precision over latency. Nightly update code written and tested but not installed; MCP server not registered yet (user: "we will register the server later").

**Update 2026-10-31 (later):** expansion experiment finished and adopted: expand_vec w=1 + bge rerank wired into server.py (`_Expansion`, lazy Gemma, idle unload, DOCSEARCH_EXPAND=off to disable). See HANDOFF.md for numbers; next is canaries re-run, then remaining failures / registration / nightly install.

**Update 2026-10-31 (night): moving to new server** (RX 7900 XTX 24 GB, 64 GB RAM). bge-m3 full re-embed on RX 6600 ran 6 chunks/s (~12 h) and was stopped at 7.5k/267k; `eval/bge_full.py` + `eval/bge_eval.py` ready, adoption bar pre-registered. Hardware re-review and porting checklist are in HANDOFF.md section "Move to the new server" (read first). Memory exported to `LLM/docsearch/handoff-memory/`. Key insight: eval set (52 q) is now the bottleneck, not compute.
