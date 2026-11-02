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

## qinc: reconstructed includes (2026-11-01)
The private `reusable-content` / `azure-dev-docs-pr` repos are not cloned, so 1,408 pages had unresolved includes. For the 9 most-used
include files (8 in `reusable-content`, 1 terraform include) the text was recovered from the rendered Learn pages (3 pages per include,
identical across pages, extracted by Haiku 5.5 agents; link URLs and exact markup are lost) and written as stand-in checkouts, see HANDOFF.md.
`docsearch update` now heals pages whose includes resolve later (977 pages reprocessed, 1,489 chunks embedded; canaries ok).
- **qset2 (no harm check)**, SERVER config, pre vs post heal, paired bootstrap: test R@5 .816 -> .816, MRR .710 -> .710 (strict) and
  .912 / .855 (lenient, both unchanged); dev R@5 .837 -> .837, MRR .743 -> .744. All CIs include 0; unanswerable AUC -0.001; p50 unchanged.
- **qinc (gain check)**: `qinc/questions.jsonl`, 48 questions (8 topics x 6; Haiku 5.5, no 5-word copy from the passage, checked by script),
  built by `qinc_build.py`, expansions by `qinc_expand.py`. Gold = every page using the include (57-260 pages per topic), split 3 dev / 3 test per topic.
  `compare.py --set qinc --split all --systems pre/server,nomic/server --baseline pre/server`: R@5 .167 -> .604 [Δ +.438, CI +.292..+.583],
  MRR .135 -> .457 [Δ +.323, +.221..+.429], nDCG@10 .069 -> .319. Test half alone R@5 .208 -> .625, dev .125 -> .583.
  By topic R@5 (pre -> post): Cloud Shell 0 -> .83, terraform init 0 -> .83, AKS preview callout .50 -> .83, Az PowerShell note .67 -> .83,
  CLI prerequisites 0 -> .50, ARM intro .17 -> .50, Bicep intro 0 -> .50, **free-trial note 0 -> 0** (generic wording; many other pages answer it, 258 gold pages never reach the top 5).
- **Terraform batch (2026-11-01)**: 6 more terraform includes (abstract, plan, plan-notes, apply-plan, plan-destroy; 24 new questions, qinc = 72).
  `--systems h1/server,nomic/server --baseline h1/server` (h1 = index before this batch, `index-20261101-195217309.db`), all 72 questions:
  R@5 .417 -> .667 [Δ +.250, CI +.139..+.361], MRR .317 -> .497 [Δ +.180, +.098..+.265], nDCG@10 .216 -> .386. Per-topic split not computed yet.
- Caveats: the questions target exactly this content (best case); n = 48 (6 per topic); model-written questions; `pre` is the index before the heal
  (`index-20261101-160916351.db`, registered in `compare.py` as `pre`; keep that file while this comparison matters).

## Phase B1: rerankers on qset2 test (2026-11-01)
`compare.py --systems nomic/server,nomic/server@<reranker>` (server = rerank top 10 rrf + expand_vec; one llama-server per reranker; scores cached per model name).
Strict R@5 / MRR / unans. AUC / p50: **bge-v2-m3 Q8 (current)** .816 / .710 / .912 / 1.3 s | Qwen3-Reranker-8B Q8 .816 / .718 / .939 / 3.4 s | Qwen3-Reranker-4B Q4 .820 / .708 / .932 / 3.1 s |
Prism-Qwen3.5-Reranker-4B Q8 (self-converted) .823 / .719 / .964 / 5.3 s. All strict deltas have CIs including 0. Lenient: Qwen3 no significant change;
Prism MRR +.017 [+.002,+.034], nDCG10 +.011 [+.003,+.020] (R@5 unchanged), strict not significant. **Not adopted** (bar: both strict and lenient, no AUC regression; latency 4x).
Prism worth revisiting for abstention (AUC .912 -> .964, few unanswerable questions in test). Prism GGUF: no public file exists; converted with llama.cpp `convert_hf_to_gguf.py`
(pre-tokenizer hash unknown -> forced `qwen35`, tokenization checked identical), scored by `Reranker._prism` (p(yes)/(p(yes)+p(no)) via /completion); model in `data/models/prism4b/` (git-ignored).

## Phase B2: embedding slice test on qset2 (2026-11-02)
`QSET=qset2 K=8 eval/embed_slice.py {pool|nomic|bge-m3|qwen3-4b|qwen3-8b}`: pool = 39,715 chunks (nomic/BM25 top-8 per question + every chunk of the gold pages + 2,500 random), vector-only ranking, page level, all qset2 questions.
Strict R@1/R@5/MRR | lenient R@5/MRR: **nomic** (768-d) .548/.802/.662 | .915/.807 — bge-m3 (1024-d) .592/.869/.712 | .972/.871 —
**Qwen3-Embedding-4B Q8** (2560-d) .719/.940/.814 | .989/.934 — Qwen3-Embedding-8B Q8 (4096-d) .730/.947/.820 | .991/.944.
Qwen3 needs `<|endoftext|>` appended to documents and queries (last-token pooling) plus the "Instruct: ... Query: " query prefix; the earlier 0.6B rejection was without EOS.
4B ~6 chunks/s (8B ~3.5/s), ROCm0 = Vulkan0 speed. Slice only: the full-pipeline test uses `data/exp-qwen3-4b.db` (`eval/qwen_full.py embed`, ~13 h) and `compare.py --systems nomic/server,q4/server`.

## Phase B4: abstention signals on qset2 (2026-11-02)
`eval/abstain.py` (cached rerank scores only, no GPU rerank): AUC of "answerable vs unanswerable" for signals derived from the top-10 rerank scores.
**bge (current)**: best single signal = max score (`confidence`): AUC dev .894 / test .914 (28 / 25 unanswerable); margin .64/.63, top-3 mean .86/.88, max/sum .71/.69; a logistic
combination fitted on dev adds nothing (test .912). Thresholds transfer dev -> test: keeping 95% / 90% / 80% of answerable on dev gives test 96/91/78% kept and 44/68/92% of unanswerable abstained.
Test only (no dev scores cached): Qwen3-8B .944, Qwen3-4B .928, **Prism-4B .967** (top-3 mean .959). With 25 unanswerable questions an AUC difference below ~.05 is not distinguishable.
Takeaway: `confidence` is already a usable abstention signal; a better reranker moves it only slightly. (The "logit" column is meaningless for bge: its scores are not probabilities.)

Shipped (2026-11-02): search results now carry `rerank_max` (raw best rerank score) and `confidence` = logistic(a * rerank_max + b), a=0.689, b=0.805 for bge-v2-m3-q8, fitted on all 575 scored qset2 questions
(522 answerable, 53 unanswerable). Held-out check (fit on dev, 281 test questions): Brier .060 vs .089 for "always answerable"; predicted .00-.50 -> observed answerable .38 (n=16),
.50-.80 -> .73 (22), .80-.95 -> .85 (61), .95-1 -> 1.00 (182). Refit whenever the reranker, embedding model or corpus changes much.
