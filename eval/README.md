# Retrieval evaluation (design section 10)

`questions.jsonl` — 58 questions (52 answerable, 6 unanswerable); built by `make_questions.py`.
Gold labels are page-level `repo/path` sources chosen from the file tree/titles/literal grep, never from search ranking.

| category | n | origin |
|---|--:|---|
| conceptual / how-to | 33 | 14 hand-written, 19 synthetic (seeded random chunk, questions paraphrase it) |
| identifier | 9 | gold = every page literally containing the token |
| variant | 6 | gold page has the variant; hit must carry `expected_variant` |
| multi_page | 4 | two gold pages each |
| unanswerable | 6 | topics absent from this checkout (Cosmos DB, AKS, Key Vault, VM SLA, off-topic) |

Run: `uv run python eval/run_eval.py [--only NAME] [--grep] [--learn] [--lenient] [--filtered] [--failures]`.
`judgments.json` holds pooled judgments added after reviewing misses; `--lenient` accepts them. Strict scores use only the original gold.

## Results (index 20261031-075641, 52 answerable questions)

| system | R@1 | R@5 | R@10 | MRR | tokens/answer | p50 |
|---|--:|--:|--:|--:|--:|--:|
| docsearch hybrid (default), strict | 0.558 | 0.846 | 0.904 | 0.692 | 2,136 | 0.95 s |
| docsearch hybrid, lenient | 0.692 | 0.923 | 0.942 | 0.800 | 2,136 | 0.95 s |
| Learn MCP (Option 0), strict | 0.269 | 0.769 | 0.865 | 0.449 | 6,976 | 0.66 s |
| grep proxy (Option 1, no agent loop), strict | 0.288 | 0.385 | 0.423 | 0.340 | – | 3.6 s |

Ablations (strict): BM25 only R@5 0.788/MRR 0.622; vector only 0.808/0.648; hybrid 0.846/0.692. Boosts, phrase queries,
field weights, rrf_k, candidate count, vector/identifier weights: all within +-0.02 MRR of the default (noise at n=52).
Dropping the identifier list was marginally better (MRR 0.711), doubling the vector weight marginally better on R@10 (0.923);
neither is a reliable win.

## Caveats (read before quoting numbers)
- n is small: 4 multi-page and 6 variant questions. Differences under ~0.03 are noise.
- Gold is drawn from this checkout, which favours the local index. 19 synthetic questions come from chunk text.
- Originally recorded as 50%; recounted 2026-10-31 on the saved results: 31% of the 580 URLs the Learn MCP returned were not in the index (177), 24% (138) after adding the AKS/Monitor/Compute/PowerShell repos. They are for pages not in this checkout; they may be valid answers that cannot be credited,
  so its MRR/R@1 are understated. On the 49 questions it can reach, R@10 ties (0.898) and R@5 is 0.796 vs 0.857.
- The grep baseline is a proxy (idf-ranked files), not an agent iterating; a real agent would do better and cost more tokens.
- Unanswerable detection is weak (AUC 0.62): top scores barely separate answerable from unanswerable queries.
