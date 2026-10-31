"""python eval/run_eval.py [--systems default,grep,...] [--filtered]   (see EXPERIMENTS below)"""
import argparse
import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
from docsearch import evalrun as E
from docsearch.config import load_config
from docsearch.search import SearchConfig
from docsearch.server import _Embeddings

D = SearchConfig()
EXPERIMENTS = {
    "default": D,
    "bm25-only (no vec, no ident)": replace(D, vector=0, ident=0),
    "bm25+ident (no vec)": replace(D, vector=0),
    "vector-only": replace(D, bm25=0, phrase=0, ident=0),
    "hybrid, no ident": replace(D, ident=0),
    "hybrid, no phrase": replace(D, phrase=0),
    "hybrid, no boosts": replace(D, boost_repo=False, boost_intent=1.0, boost_service=1.0, boost_recency=0.0),
    "hybrid, no intent/service boost": replace(D, boost_intent=1.0, boost_service=1.0),
    "fields 1,1,1,1": replace(D, fields="1, 1, 1, 1"),
    "fields 20,5,3,1": replace(D, fields="20, 5, 3, 1"),
    "fields 10,5,5,1": replace(D, fields="10, 5, 5, 1"),
    "rrf_k=20": replace(D, rrf_k=20),
    "rrf_k=120": replace(D, rrf_k=120),
    "vector weight 2": replace(D, vector=2.0),
    "vector weight 0.5": replace(D, vector=0.5),
    "ident weight 2": replace(D, ident=2.0),
    "candidates=100": replace(D, candidates=100),
    "no variant grouping": replace(D, group_variants=False),
    "per_doc=1": replace(D, per_doc=1),
    "per_doc=3": replace(D, per_doc=3),
}

ap = argparse.ArgumentParser()
ap.add_argument("--only", help="comma-separated experiment names (substring match); default: all")
ap.add_argument("--grep", action="store_true", help="also run the grep-proxy baseline")
ap.add_argument("--learn", action="store_true", help="also run the hosted Learn MCP baseline (network)")
ap.add_argument("--filtered", action="store_true", help="give variant questions their pivot/tab filter")
ap.add_argument("--lenient", action="store_true", help="also accept the pooled judgments in eval/judgments.json")
ap.add_argument("--failures", action="store_true")
ap.add_argument("--db", default=str(HERE / "data" / "current.db"))
ap.add_argument("--tag", default="run")
a = ap.parse_args()

cfg = load_config(HERE / "repos.toml")
qs = E.load_questions(lenient=a.lenient)
emb = _Embeddings()
memo = {}
def embed(q):
    if q not in memo:
        memo[q] = emb(q)
    return memo[q]
for q in qs:                     # warm: start server + cache every question embedding once
    embed(q["question"])

print(f"{len(qs)} questions ({sum(q['answerable'] for q in qs)} answerable); db={Path(a.db).resolve().name}; filtered={a.filtered}; {'LENIENT (pooled judgments)' if a.lenient else 'STRICT (original gold)'}\n")
print(E.HEADER)
results = {}
names = list(EXPERIMENTS)
if a.only:
    keys = [k.strip() for k in a.only.split(",")]
    names = [n for n in names if any(k in n for k in keys)]
for name in names:
    s = E.DocsearchSystem(Path(a.db), embed, cfg, EXPERIMENTS[name], name, measure=(name == 'default'))
    summ, rows = E.run_system(s, qs, a.filtered)
    results[name] = {"summary": summ, "rows": rows, "config": asdict(EXPERIMENTS[name])}
    print(E.fmt_row(name, summ), flush=True)
if a.grep:
    summ, rows = E.run_system(E.GrepProxySystem(cfg), qs, a.filtered, workers=4)
    results["grep-proxy"] = {"summary": summ, "rows": rows}; print(E.fmt_row("grep-proxy (Option 1, no agent)", summ))
if a.learn:
    L = E.LearnMcpSystem(Path(a.db)); L.prefetch(qs)
    summ, rows = E.run_system(L, qs, a.filtered)
    results["learn-mcp"] = {"summary": summ, "rows": rows}; print(E.fmt_row("learn-mcp (Option 0, hosted)", summ))

print("\nPer category (R@5 / MRR):")
cats = sorted({c for r in results.values() for c in r["summary"]["by_cat"]})
print(f"{'system':34s} " + " ".join(f"{c:>18s}" for c in cats))
for name, r in results.items():
    print(f"{name:34s} " + " ".join(f"{r['summary']['by_cat'][c]['R@5']:.2f} / {r['summary']['by_cat'][c]['MRR']:.2f}".rjust(18) for c in cats))
if a.failures:
    first = next(iter(results.values()))
    byid = {q["id"]: q for q in qs}
    print("\nMisses in top-10 for", next(iter(results)), ":")
    for r in first["rows"]:
        if r["category"] != "unanswerable" and not r["r10"]:
            print(f"  {r['id']} [{r['category']}] rank={r['rank']} :: {byid[r['id']]['question'][:80]}")
out = HERE / "eval" / "results"; out.mkdir(parents=True, exist_ok=True)
(out / f"{time.strftime('%Y%m%d-%H%M%S')}-{a.tag}.json").write_text(json.dumps(results, default=str))
