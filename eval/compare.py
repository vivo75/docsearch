"""Compare retrieval systems on an eval split with paired bootstrap confidence intervals.

  uv run python eval/compare.py --systems nomic/server,bge/server [--set qset2] [--split test] [--baseline nomic/server]

Each system searches every question once; the ranking is scored against the strict gold and the lenient gold
(gold + pooled grade-2 judgments). For each system other than the baseline it prints the mean difference and a 95% paired
bootstrap CI (resampling questions) for R@5, MRR and nDCG@10. Adoption rule (eval/README.md, "Adoption rule"): decide on
--split test only.

Systems are "<index>/<config>": index in INDEXES (nomic = data/current.db, rebuild = data/rebuild-nomic/current.db,
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
from docsearch.embed import BgeServer, Embedder
from docsearch.expand import QueryExpander
from docsearch.rerank import Reranker, RerankServer
from docsearch.search import SearchConfig
from docsearch.server import SERVER_CONFIG, _Embeddings

H = Path(__file__).resolve().parents[1]; Q2 = H / "eval" / "qset2"; R = H / "eval" / "results"
D = SearchConfig()
# nomic = the live index (since 2026-11-01 the extended corpus, same file as c2); c1 = the original 14-repo corpus
INDEXES = {"nomic": (H / "data" / "current.db", "nomic"), "c1": (H / "data" / "index-20261031-144038161.db", "nomic"), "rebuild": (H / "data" / "rebuild-nomic" / "current.db", "nomic"),
           "bge": (H / "data" / "exp-bge-m3.db", "bge"), "c2": (H / "data" / "corpus2" / "current.db", "nomic"),
           # pre = live index before the reconstructed-include heal (2026-11-01 16:09); nomic = after it
           "pre": (H / "data" / "index-20261101-160916351.db", "nomic"),
           # h1 = after the first 9 reconstructed includes, before the terraform family (2026-11-01 19:52)
           "h1": (H / "data" / "index-20261101-195217309.db", "nomic")}
CONFIGS = {"bm25": (replace(D, vector=0), False), "vector": (replace(D, bm25=0, phrase=0, ident=0), False), "hybrid": (D, False),
           "rerank": (SERVER_CONFIG, True), "expand": (replace(D, expand_vec=1.0), True),
           "server": (replace(SERVER_CONFIG, expand_vec=1.0), True)}       # server = what `docsearch serve` runs
METRICS = ("r1", "r5", "r10", "mrr", "ndcg10")



def load(set_name: str, split: str, judgments: str | None = None):
    if set_name in ("qset2", "qset3", "qinc"):
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


def auc(rows):
    an = [r["top_score"] for r in rows if r["category"] != "unanswerable"]; un = [r["top_score"] for r in rows if r["category"] == "unanswerable"]
    if not an or not un: return None
    return sum((a > u) + 0.5 * (a == u) for a in an for u in un) / (len(an) * len(un))


def boot(a: np.ndarray, b: np.ndarray, n: int, rng) -> tuple[float, float, float]:
    d = a - b; idx = rng.integers(0, len(d), size=(n, len(d)))
    m = d[idx].mean(1)
    return float(d.mean()), float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="nomic/server,bge/server")
    ap.add_argument("--baseline", help="default: the first system")
    ap.add_argument("--set", default="qset2", choices=["qset2", "qset3", "qinc", "v1"])
    ap.add_argument("--split", default="test", choices=["test", "dev", "all"])
    ap.add_argument("--boot", type=int, default=10000)
    ap.add_argument("--judgments", help="qset2 lenient judgment file (default judgments-c2.json, the live extended corpus; judgments.json = original corpus only)")
    a = ap.parse_args()
    names = [s.strip() for s in a.systems.split(",")]; base = a.baseline or names[0]
    strict, lenient = load(a.set, a.split, a.judgments); lmap = {q["id"]: q for q in lenient}
    print(f"set={a.set} split={a.split}: {len(strict)} questions ({sum(q['answerable'] for q in strict)} answerable)", flush=True)

    texts = [q["question"] for q in strict]
    ex = QueryExpander("", (H / "eval" / a.set if a.set != "v1" else Q2) / "expansions.json")
    if any(CONFIGS[n.split("/")[1]][1] for n in names):
        missing = [t for t in texts if t not in ex.cache]
        if missing: raise SystemExit(f"{len(missing)} questions have no cached expansion (run qset2.py pool first)")
    kinds = {INDEXES[n.split("/")[0]][1] for n in names}
    memo = {}
    if "nomic" in kinds:
        e = _Embeddings(); memo["nomic"] = {t: e(t) for t in {s for q in texts for s in (q, q + " " + ex.cache.get(q, ""))}}
    if "bge" in kinds:
        with BgeServer() as bs:
            e = Embedder(bs.url, workers=1); memo["bge"] = {t: e.embed([t], "")[0] for t in {s for q in texts for s in (q, q + " " + ex.cache.get(q, ""))}}
    cfg = load_config(H / "repos.toml")

    def evaluate(rr):
        out = {}
        for n in names:
            idx, conf = n.split("/"); db, kind = INDEXES[idx]; config, needs_rr = CONFIGS[conf]
            s = E.DocsearchSystem(db, memo[kind].__getitem__, cfg, config, n, measure=True,
                                  reranker=(lambda q, d: rr.score(q, d)) if needs_rr else None, expander=lambda q: ex.cache[q])
            rows_s, rows_l, lat = [], [], []
            for q in strict:
                res = s.run(q); lat.append(res["latency_ms"])
                rows_s.append(E.score_question(q, res)); rows_l.append(E.score_question(lmap[q["id"]], res))
            out[n] = {"strict": rows_s, "lenient": rows_l, "p50_ms": float(np.median(lat))}
            print(f"  ran {n}", flush=True)
        return out

    if any(CONFIGS[n.split("/")[1]][1] for n in names):
        with RerankServer("bge-v2-m3-q8") as rs:
            res = evaluate(Reranker(rs.url, "bge-v2-m3-q8", cache=(H / "eval" / a.set if a.set != "v1" else Q2) / "rerank_cache.jsonl"))
    else:
        res = evaluate(None)

    rng = np.random.default_rng(20261101); report = {"set": a.set, "split": a.split, "baseline": base, "systems": {}}
    for mode in ("strict", "lenient"):
        print(f"\n== {mode.upper()} ({a.split}) ==")
        print(f"| {'system':18s} |  R@1  |  R@5  | R@10  |  MRR  |nDCG10 | var.acc| unans.AUC| p50 ms |")
        for n in names:
            rows = [r for r in res[n][mode] if r["category"] != "unanswerable"]
            m = {k: float(np.mean([r[k] for r in rows])) for k in METRICS}
            va = [r["variant_ok"] for r in rows if "variant_ok" in r]; u = auc(res[n][mode])
            m.update(variant_acc=float(np.mean(va)) if va else None, unans_auc=u, n=len(rows), p50_ms=res[n]["p50_ms"])
            report["systems"].setdefault(n, {})[mode] = m
            print(f"| {n:18s} | {m['r1']:.3f} | {m['r5']:.3f} | {m['r10']:.3f} | {m['mrr']:.3f} | {m['ndcg10']:.3f} | "
                  f"{(m['variant_acc'] or 0):.3f} | {u if u is None else round(u, 3)!s:>8} | {m['p50_ms']:6.0f} |")
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


if __name__ == "__main__":
    main()
