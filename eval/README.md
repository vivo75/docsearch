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

## bge-m3 full-corpus test (2026-10-31, RX 7900 XTX) — NOT adopted
`eval/bge_full.py embed` re-embedded all 267,518 chunks with bge-m3 Q8 (ROCm0, cls pooling, no prefixes) in 83 min
(53.6 chunks/s; the RX 6600 ran 6/s). `eval/bge_eval.py`, same questions, cached expansions, bge-v2-m3 rerank, configs fixed in advance.
Log: `data/bge-eval.log`; summary json in `results/*-bge-vs-nomic.json`. Index kept at `data/exp-bge-m3.db` for re-tests on a larger eval set.

| SERVER config (expand_vec + rerank) | R@1 | R@5 | R@10 | MRR | nDCG@10 | var.acc | unans.AUC |
|---|---|---|---|---|---|---|---|
| nomic, strict | .654 | .885 | .942 | .757 | .785 | 1.000 | .490 |
| bge-m3, strict | .654 | .923 | .942 | .760 | .791 | .833 | .513 |
| nomic, lenient | .750 | .942 | .942 | .833 | .837 | 1.000 | .490 |
| bge-m3, lenient | .712 | .962 | .962 | .808 | .820 | .833 | .513 |

Pre-registered bar: >= 2 more questions at R@5 (or clearly higher MRR) on BOTH strict and lenient, no AUC/canary regression.
Strict: +2 questions at R@5, MRR flat. Lenient: +1 question at R@5, MRR -.025, R@1 -.038. Variant accuracy 1.0 -> .833 (1 of 6).
Canaries 15/15 both; AUC ~.5 both. **Fails the bar on lenient** -> stay on nomic. Per-question churn is large in both directions
(q008 11->4, q006 7->2, q020 3->1; q015 10->miss, q024 2->4, several 1->2): the models disagree more than the totals suggest,
which is a reason to re-run this on a bigger eval set rather than to declare bge-m3 worse.
Nomic numbers on the copied index reproduce the old machine (strict R@5 .885, MRR .757 vs .753; lenient .942 / .833 vs .838).
Without the rerank stage bge-m3 is no better anywhere (hybrid strict MRR .672 vs .676) except vector-only R@10 (.942 vs .865).

## qset2: larger question set (2026-11-01)
`qset2/questions.jsonl`: 626 questions (566 answerable + 60 unanswerable), split dev 313 / test 313; built by `qset2.py`
(Qwen3.8-27B generation from stratified pages, grounding/lexical-leak/near-duplicate filters, pooled judgments by gemma-4-26B-A4B,
17,524 graded pairs). The v1 58 questions stay dev-only; `qset2/judgments_v1.json` re-judges them with the same rules.
Use **test** only for adoption decisions.

Human review of 50 sampled items (`qset2/review.md`, applied via `qset2/human_review.json`):
- questions realistic 25/25; strict gold correct 21/25 (vague question, identifier whose literal-match gold does not explain it
  [excluded], better pages exist for a comparison, one unanswerable that is answerable on Learn);
- judge agreement 24/25 (one grade-2 that should be 1: another service's "support and help" page);
- **12 of the 20 extra pages the reviewer named are not in the corpus**: Azure CLI reference (`cli/azure/*`), Azure IoT Operations,
  support articles (`troubleshoot/azure/*`), .NET API reference, Cosmos DB. Coverage, not ranking, limits these questions.

v1 findings: 4 of the 6 v1 "unanswerable" questions now have grade-2 pages (AKS docs were added; Cosmos DB / Key Vault / VM SLA have
partial answers in architecture, backup and SAP pages), so v1 unanswerable AUC numbers used wrong labels. 45/52 v1 answerable gold
pages get grade 2 from the judge (most of the rest are single pages of two-page comparisons, graded 1 correctly).

## Adoption rule (pre-registered 2026-11-01, before any qset2 test run)
Tool: `eval/compare.py --set qset2 --split test --systems <current>,<candidate>` (paired bootstrap over questions, 10,000 resamples).
A candidate replaces the current server configuration only if, on the **qset2 test split**:
1. the 95% CI of ΔMRR is entirely above 0 on **both** strict and lenient scoring;
2. no 95% CI of ΔR@5 or ΔnDCG@10 (strict or lenient) lies entirely below 0;
3. unanswerable AUC does not drop by more than 0.05, variant accuracy does not drop by more than 0.05;
4. canaries pass (15/15).
Latency is reported but is not a gate (user priority: precision over latency). Tuning and exploration use the dev split
(qset2 dev + v1); the test split is run once per decision. A candidate that fails stays available for re-test only on a new
or enlarged test set, not by retuning on this one.

## Decision run: bge-m3 on qset2 test (2026-11-01) — NOT adopted
`compare.py --set qset2 --split test` (300 answerable + 13 unanswerable test questions; log `results/compare-test.log`):
bge/server vs nomic/server ΔMRR strict -0.008 [-0.033, +0.018], lenient +0.003 [-0.018, +0.024] -> rule 1 fails.
ΔR@5 +0.021 / +0.018 and ΔnDCG +0.007 / +0.017 (CIs include 0); p50 latency 1.47 s vs 1.10 s. Same verdict as the v1 run,
now with CIs about half as wide (±0.025 MRR). The rebuilt nomic index equals the copied one (all Δ ≈ 0).
Observations for dev-split work (not decisions): the server config beats plain hybrid at rank 1 (R@1 .618 vs .572) but not at
R@5 (.806 vs .823): reranking pushes some gold pages out of the top 5; it raises unanswerable AUC (.90 vs .65). Variant accuracy
on qset2 is low (~.64): the right page is found but the hit carries the wrong tab/pivot.

## Corpus extension on qset2 test (2026-11-01) — rule 1 not met; decision left to the user
`compare.py --split test --judgments judgments-c2.json` (corpus2 = current corpus + Azure CLI docs/reference + support articles;
1,030 new pairs judged; 2 unanswerable test questions became answerable on corpus2 and leave the AUC; 283 answerable):
c2/server vs nomic/server ΔMRR strict +0.001 [-0.008, +0.010], lenient +0.005 [-0.001, +0.013] -> rule 1 fails;
ΔR@5 +0.011 / +0.014 (CIs from 0), ΔnDCG lenient +0.015 [+0.006, +0.026] (CI above 0); no metric worse; AUC .907 -> .913;
canaries pass; p50 1.10 -> 1.24 s.
Caveat: qset2 questions were generated from pages of the original corpus, so its strict gold cannot contain the new pages; the
set measures "no harm" here, not the coverage gain that motivated the change (12 of 20 reviewer pages were outside the corpus).
**Adopted by the user 2026-11-01** ("adopt now, measure after"): `data/current.db` -> `index-20261101-160916351.db` (299,349
chunks, 17 repos). Previous live index kept: `index-20261031-144038161.db` (`compare.py` name `c1`); roll back with
`ln -sfn index-20261031-144038161.db data/current.db`. Default lenient judgments for compare.py are now `judgments-c2.json`.
Follow-up: a question set generated from the NEW pages, to measure the coverage gain this test set cannot see.

## qset3: coverage gain of the corpus additions (2026-11-01)
95 questions written from 112 sampled pages of the three added sources (36 CLI reference, 19 CLI docs, 40 support articles; all
judged-2 on their source page), `compare.py --set qset3`, c1 = corpus before the additions, nomic = live corpus (server config).
**Strict is meaningless for c1 (0.000 by construction: the gold page is not in that index). Read the lenient rows.**
Lenient: R@5 0.505 -> 0.874 [ΔR@5 +0.368, 95% CI +0.274..+0.463], MRR 0.430 -> 0.776 [Δ +0.346, +0.258..+0.436],
nDCG@10 0.276 -> 0.621. For 61 of 95 questions the old corpus also held a grade-2 page (25/36 CLI reference, 12/19 CLI docs,
24/40 support): the additions were needed for 34 (36%). Latency p50 1.11 -> 1.24 s.
Caveat: the questions are drawn from the new pages, so this is the best case for the addition; qset2 test (drawn from the old
corpus) shows no harm. Together they support the adoption made on 2026-11-01.
