"""Compare retrieval systems on an eval split with paired bootstrap confidence intervals.

  uv run python eval/compare.py --systems nomic/server,bge/server [--set qset2] [--split test] [--baseline nomic/server]

Each system searches every question once; the ranking is scored against the strict gold and the lenient gold
(gold + pooled grade-2 judgments). For each system other than the baseline it prints the mean difference and a 95% paired
bootstrap CI (resampling questions) for R@5, MRR and nDCG@10. Adoption rule (eval/README.md, "Adoption rule"): decide on
--split test only.

Systems are "<index>/<config>": index in INDEXES (nomic = data/exp-nomic-baseline.db, live = data/current.db (Qwen3-4B since the promotion), rebuild = data/rebuild-nomic/current.db,
bge = data/exp-bge-m3.db), config in CONFIGS. Expansions and rerank scores come from the qset2 caches (no Gemma needed).
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from docsearch import evalrun as E
from docsearch.config import load_config
from docsearch.embed import BgeServer, Embedder, QwenServer, qwen_query
from docsearch.expand import QueryExpander
from docsearch.rerank import Reranker, RerankServer
from docsearch.search import SearchConfig
from docsearch.server import SERVER_CONFIG
from legacy import NomicQueries as _Embeddings

H = Path(__file__).resolve().parents[1]; Q2 = H / "eval" / "qset2"; R = H / "eval" / "results"
D = SearchConfig()
# nomic = the live index (since 2026-11-01 the extended corpus, same file as c2); c1 = the original 14-repo corpus
INDEXES = {"preaks": (H / "data" / "index-20261105-154235678.db", "qwen4b"),   # live index before the AKS release notes + Kubernetes upstream docs (2026-11-05)
           "pretf": (H / "data" / "index-20261105-133125352.db", "qwen4b"),   # live index before the azurerm provider docs were added (2026-11-05)
           "nomic": (H / "data" / "exp-nomic-baseline.db", "nomic"),   # nomic baseline = the live index of 2026-11-02 04:02 (until Qwen3 went live)
           "live": (H / "data" / "current.db", "qwen4b"),
           # prem = Qwen3 index before the horz-monitor includes were recovered (2026-11-02 22:31); keep this file while the qmon comparison matters
           "prem": (H / "data" / "exp-qwen3-premon.db", "qwen4b"), "c1": (H / "data" / "index-20261031-144038161.db", "nomic"), "rebuild": (H / "data" / "rebuild-nomic" / "current.db", "nomic"),
           "bge": (H / "data" / "exp-bge-m3.db", "bge"), "c2": (H / "data" / "corpus2" / "current.db", "nomic"),
           # pre = live index before the reconstructed-include heal (2026-11-01 16:09); nomic = after it
           "pre": (H / "data" / "index-20261101-160916351.db", "nomic"),
           # h1 = after the first 9 reconstructed includes, before the terraform family (2026-11-01 19:52)
           "h1": (H / "data" / "index-20261101-195217309.db", "nomic"),
           # q4/q8 = full-corpus Qwen3-Embedding experiments (eval/qwen_full.py embed): a copy of the live index with 2560-d / 4096-d vectors
           "q4": (H / "data" / "exp-qwen3-4b.db", "qwen4b"), "q8": (H / "data" / "exp-qwen3-8b.db", "qwen8b")}
CONFIGS = {"bm25": (replace(D, vector=0), False), "vector": (replace(D, bm25=0, phrase=0, ident=0), False), "hybrid": (D, False),
           "rerank": (SERVER_CONFIG, True), "expand": (replace(D, expand_vec=1.0), True),
           "server": (replace(SERVER_CONFIG, expand_vec=1.0), True)}       # server = what `docsearch serve` runs
           # server0 = server without the variant boost (ablation, B8); keep while the boost decision matters
CONFIGS["server0"] = (replace(SERVER_CONFIG, expand_vec=1.0, variant_boost=0.0), True)
# near-duplicate merging before the rerank (Jaccard thresholds .9/.8/.7); the trailing x credits the pages listed in also_in at the representative's rank
for _t in (9, 8, 7):
    CONFIGS[f"dd{_t}"] = (replace(CONFIGS["server"][0], dedup=_t / 10), True)
    CONFIGS[f"dd{_t}x"] = CONFIGS[f"dd{_t}"]
# multi-query: the caller adds rewrites (eval/<set>/rewrites.json: id -> {kw, alt}, written blind to the gold by another model)
for _p in (90, 80, 65, 50):
    CONFIGS[f"news{_p}"] = (replace(CONFIGS["server"][0], news_penalty=_p / 100), CONFIGS["server"][1])
for _b in (15, 20, 30):
    CONFIGS[f"svc{_b}"] = (replace(CONFIGS["server"][0], boost_service=_b / 10), CONFIGS["server"][1])
for _f in (20, 30):          # rerank window widened until the reranked chunks collapse to `limit` hits (Backlog 1)
    CONFIGS[f"fill{_f}"] = (replace(CONFIGS["server"][0], rerank_fill=_f), CONFIGS["server"][1])
CONFIGS["server_mq"] = CONFIGS["server"]; CONFIGS["server_mq1"] = CONFIGS["server"]
MQ = {"server_mq": ("kw", "alt"), "server_mq1": ("kw",)}
CREDIT = {"dd9x", "dd8x", "dd7x"}
METRICS = ("r1", "r5", "r10", "mrr", "ndcg10")



def load(set_name: str, split: str, judgments: str | None = None):
    if set_name in ("qset2", "qset3", "qinc", "qmon", "qset4", "qreal"):
        Qd = H / "eval" / set_name
        jf = Qd / (judgments or ("judgments-c2.json" if set_name == "qset2" else "judgments.json"))
        for f in (Qd / "questions.jsonl", jf):
            if not f.exists():
                raise SystemExit(f"{f.relative_to(H)} is missing: build it with `QSET={set_name} uv run python eval/qset2.py "
                                 f"finalize{'-new' if set_name == 'qset3' else ''}` (judgments-c2.json: `qset2.py lenient --tag c2`)")
        strict = E.load_questions(Qd / "questions.jsonl"); lenient = E.load_questions(Qd / "questions.jsonl")
        J = json.loads((Qd / (judgments or ("judgments-c2.json" if set_name == "qset2" else "judgments.json"))).read_text())   # lenient gold for the live (extended) corpus
        now = set(J.get("_now_answerable", {}))
        for q in lenient: q["gold"] = sorted({*q["gold"], *J.get(q["id"], {}).get("also_ok", [])})
        # unanswerable questions that this corpus can answer: not unanswerable any more -> out of the AUC (and of scoring)
        strict = [q for q in strict if q["id"] not in now]; lenient = [q for q in lenient if q["id"] not in now]
    else:
        strict = E.load_questions(); lenient = E.load_questions(lenient=True)
        for q in strict + lenient: q["split"] = "dev"
    keep = lambda qs: [q for q in qs if split == "all" or q.get("split") == split]
    return keep(strict), keep(lenient)


def parse(n: str):
    """`index/config[@reranker[:chars]]` -> (index, config, reranker[:chars]); reranker defaults to the server's bge-v2-m3-q8 with its
    default text length (rerank.Reranker.max_chars); `@bge-v2-m3-q8:3000` gives the cross-encoder the first 3000 characters of each chunk."""
    idx, conf = n.split("/"); conf, _, rr = conf.partition("@")
    return idx, conf, rr or "bge-v2-m3-q8"


def auc(rows):
    an = [r["top_score"] for r in rows if r["category"] != "unanswerable"]; un = [r["top_score"] for r in rows if r["category"] == "unanswerable"]
    if not an or not un: return None
    return sum((a > u) + 0.5 * (a == u) for a in an for u in un) / (len(an) * len(un))


def boot(a: np.ndarray, b: np.ndarray, n: int, rng) -> tuple[float, float, float]:
    d = a - b; idx = rng.integers(0, len(d), size=(n, len(d)))
    m = d[idx].mean(1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def gate(report: dict, base: str, a, out: Path) -> int:
    """Rules 1-3 of the pre-registered adoption rule (canaries, rule 4, run in `docsearch update --canary`). Only a test-split run can adopt."""
    fails: dict[str, list[str]] = {}
    for n, rep in report["systems"].items():
        if n == base:
            continue
        bad = fails.setdefault(n, [])
        if a.split != "test":
            bad.append(f"split is {a.split}: only a run on the test split can adopt a candidate")
        for mode in ("strict", "lenient"):
            m, b = rep[mode], report["systems"][base][mode]
            if not m["delta_mrr"][1] > 0:
                bad.append(f"rule 1 ({mode}): dMRR {m['delta_mrr'][0]:+.3f} CI [{m['delta_mrr'][1]:+.3f}, {m['delta_mrr'][2]:+.3f}] is not entirely above 0")
            for k in ("r5", "ndcg10"):
                if m[f"delta_{k}"][2] < 0:
                    bad.append(f"rule 2 ({mode}): d{k} CI [{m[f'delta_{k}'][1]:+.3f}, {m[f'delta_{k}'][2]:+.3f}] lies entirely below 0")
            for key, label in (("unans_auc", "unanswerable AUC"), ("variant_acc", "variant accuracy")):
                if m[key] is not None and b[key] is not None and b[key] - m[key] > 0.05:
                    bad.append(f"rule 3 ({mode}): {label} {b[key]:.3f} -> {m[key]:.3f} drops by more than 0.05")
    failed = {n: b for n, b in fails.items() if b}
    print("\n== ADOPTION GATE ==")
    for n, b in fails.items():
        print(f"  {n}: {'PASS' if not b else 'FAIL'}")
        for line in b:
            print(f"      - {line}")
    if failed and a.override:
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "result": str(out.relative_to(H)), "set": report["set"], "split": report["split"],
               "baseline": base, "failed": failed, "override_reason": a.override}
        with open(H / "eval" / "decisions.jsonl", "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"  OVERRIDDEN: recorded in eval/decisions.jsonl ({a.override!r})")
        return 0
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="nomic/server,bge/server")
    ap.add_argument("--baseline", help="default: the first system")
    ap.add_argument("--set", default="qset2", choices=["qset2", "qset3", "qinc", "qmon", "qset4", "qreal", "v1"])
    ap.add_argument("--split", default="test", choices=["test", "dev", "all"])
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--rewrites", type=Path, help="JSON id -> {kw, alt} for the server_mq / server_mq1 systems")
    ap.add_argument("--gate", action="store_true", help="apply the pre-registered adoption rule (README 'Adoption rule', rules 1-3) to every candidate vs the baseline; exit 1 if any fails")
    ap.add_argument("--override", help="with --gate: adopt anyway; the reason is appended with the failed criteria to eval/decisions.jsonl")
    ap.add_argument("--judgments", help="qset2 lenient judgment file (default judgments-c2.json, the live extended corpus; judgments.json = original corpus only)")
    a = ap.parse_args()
    names = [s.strip() for s in a.systems.split(",")]; base = a.baseline or names[0]
    strict, lenient = load(a.set, a.split, a.judgments); lmap = {q["id"]: q for q in lenient}
    print(f"set={a.set} split={a.split}: {len(strict)} questions ({sum(q['answerable'] for q in strict)} answerable)", flush=True)

    texts = [q["question"] for q in strict]
    rw = json.loads(a.rewrites.read_text()) if a.rewrites else {}
    if any(parse(n)[1] in MQ for n in names) and not rw:
        raise SystemExit("server_mq systems need --rewrites")
    xq = {q["id"]: [rw[q["id"]][k] for k in ("kw", "alt") if q["id"] in rw] for q in strict}
    extra_texts = [t for v in xq.values() for t in v]
    ex = QueryExpander("", (H / "eval" / a.set if a.set != "v1" else Q2) / "expansions.json")
    if any(CONFIGS[parse(n)[1]][1] for n in names):
        missing = [t for t in texts if t not in ex.cache]
        if missing: raise SystemExit(f"{len(missing)} questions have no cached expansion (run qset2.py pool first)")
    kinds = {INDEXES[parse(n)[0]][1] for n in names}
    memo = {}
    if "nomic" in kinds:
        e = _Embeddings(); memo["nomic"] = {t: e(t) for t in {s for q in texts for s in (q, q + " " + ex.cache.get(q, ""))} | set(extra_texts)}
    if "bge" in kinds:
        with BgeServer() as bs:
            e = Embedder(bs.url, workers=1); memo["bge"] = {t: e.embed([t], "")[0] for t in {s for q in texts for s in (q, q + " " + ex.cache.get(q, ""))} | set(extra_texts)}
    for kind in ("qwen4b", "qwen8b"):
        if kind in kinds:
            with QwenServer(kind[4:]) as qs:
                e = Embedder(qs.url, workers=1)
                memo[kind] = {t: e.embed([qwen_query(t)], "")[0] for t in {s for q in texts for s in (q, q + " " + ex.cache.get(q, ""))} | set(extra_texts)}
    cfg = load_config(H / "repos.toml")

    def evaluate(todo, rr):
        out = {}
        for n in todo:
            idx, conf, _ = parse(n); db, kind = INDEXES[idx]; config, needs_rr = CONFIGS[conf]
            s = E.DocsearchSystem(db, memo[kind].__getitem__, cfg, config, n, measure=True, credit_also_in=conf in CREDIT,
                                  reranker=(lambda q, d: rr.score(q, d)) if needs_rr else None, expander=lambda q: ex.cache[q],
                                  extras={i: [v for k, v in zip(("kw", "alt"), vs) if k in MQ.get(conf, ())] for i, vs in xq.items()} if conf in MQ else None)
            rows_s, rows_l, lat = [], [], []
            for q in strict:
                res = s.run(q); lat.append(res["latency_ms"])
                rows_s.append(E.score_question(q, res)); rows_l.append(E.score_question(lmap[q["id"]], res))
            out[n] = {"strict": rows_s, "lenient": rows_l, "p50_ms": float(np.median(lat))}
            print(f"  ran {n}", flush=True)
        return out

    res = evaluate([n for n in names if not CONFIGS[parse(n)[1]][1]], None)
    wanted = [n for n in names if CONFIGS[parse(n)[1]][1]]
    for model in dict.fromkeys(parse(n)[2].partition(":")[0] for n in wanted):               # one llama-server per reranker model
        with RerankServer(model) as rs:
            for rname in dict.fromkeys(parse(n)[2] for n in wanted if parse(n)[2].partition(":")[0] == model):
                _, _, chars = rname.partition(":")                                          # caches are keyed by model name and the (cut) text
                kw = {"max_chars": int(chars)} if chars else {}
                res.update(evaluate([n for n in wanted if parse(n)[2] == rname],
                                    Reranker(rs.url, model, cache=(H / "eval" / a.set if a.set != "v1" else Q2) / "rerank_cache.jsonl", **kw)))
    res = {n: res[n] for n in names}

    rng = np.random.default_rng(20261101); report = {"set": a.set, "split": a.split, "baseline": base, "systems": {}}
    for mode in ("strict", "lenient"):
        print(f"\n== {mode.upper()} ({a.split}) ==")
        print(f"| {'system':18s} |  R@1  |  R@5  | R@10  |  MRR  |nDCG10 | var.acc| unans.AUC| p50 ms | dup10 |")
        for n in names:
            rows = [r for r in res[n][mode] if r["category"] != "unanswerable"]
            m = {k: float(np.mean([r[k] for r in rows])) for k in METRICS}
            va = [r["variant_ok"] for r in rows if "variant_ok" in r]; u = auc(res[n][mode])
            m["dup10"] = float(np.mean([r.get("dup10", 0) for r in rows])); m.update(variant_acc=float(np.mean(va)) if va else None, unans_auc=u, n=len(rows), p50_ms=res[n]["p50_ms"])
            report["systems"].setdefault(n, {})[mode] = m
            print(f"| {n:18s} | {m['r1']:.3f} | {m['r5']:.3f} | {m['r10']:.3f} | {m['mrr']:.3f} | {m['ndcg10']:.3f} | "
                  f"{(m['variant_acc'] or 0):.3f} | {u if u is None else round(u, 3)!s:>8} | {m['p50_ms']:6.0f} | {m['dup10']:5.2f} |")
        for n in names:
            if n == base: continue
            A = {r["id"]: r for r in res[n][mode] if r["category"] != "unanswerable"}
            B = {r["id"]: r for r in res[base][mode] if r["category"] != "unanswerable"}
            ids = sorted(A); line = []
            for k in ("r5", "mrr", "ndcg10"):
                d, lo, hi = boot(np.array([A[i][k] for i in ids], float), np.array([B[i][k] for i in ids], float), a.boot, rng)
                report["systems"][n][mode][f"delta_{k}"] = [d, lo, hi]
                flag = "+" if lo > 0 else "-" if hi < 0 else "~"
                line.append(f"{k} {d:+.3f} [{lo:+.3f}, {hi:+.3f}]{flag}")
            print(f"  {n} vs {base}: " + "   ".join(line))
    out = R / f"{time.strftime('%Y%m%d-%H%M%S')}-compare-{a.set}-{a.split}.json"
    out.write_text(json.dumps({**report, "rows": {n: res[n] for n in names}}, default=str))
    print(f"\nwrote {out.relative_to(H)}  (+ = CI above 0, - = below 0, ~ = includes 0)")
    if a.gate:
        raise SystemExit(gate(report, base, a, out))


if __name__ == "__main__":
    main()
