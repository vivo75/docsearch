"""python eval/rerank_eval.py MODEL [--tops 10,20,30] [--modes replace,rrf1,rrf2]  -> table rows (strict then lenient)"""
import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
from docsearch import evalrun as E
from docsearch.config import load_config
from docsearch.rerank import Reranker, RerankServer
from docsearch.search import SearchConfig
from docsearch.server import _Embeddings

ap = argparse.ArgumentParser()
ap.add_argument("model")
ap.add_argument("--tops", default="10,20,30")
ap.add_argument("--modes", default="replace,rrf1,rrf2")
ap.add_argument("--max-chars", type=int, default=2400)
ap.add_argument("--db", default=str(HERE / "data" / "current.db"))
a = ap.parse_args()

cfg = load_config(HERE / "repos.toml")
emb, memo = _Embeddings(), {}
embed = lambda q: memo.setdefault(q, emb(q))
MODES = {"replace": ("replace", 1.0), "rrf1": ("rrf", 1.0), "rrf2": ("rrf", 2.0)}
results = {}
with RerankServer(a.model) as srv:
    rr = Reranker(srv.url, a.model, max_chars=a.max_chars, cache=HERE / "eval" / "results" / "rerank_cache.jsonl")
    for lenient in (False, True):
        qs = E.load_questions(lenient=lenient)
        for q in qs: embed(q["question"])
        print(f"\n== {a.model} — {'LENIENT' if lenient else 'STRICT'} ==")
        print(E.HEADER)
        base = E.DocsearchSystem(Path(a.db), embed, cfg, SearchConfig(), measure=False)
        s0, _ = E.run_system(base, qs); print(E.fmt_row("no rerank (default)", s0), flush=True)
        for top in map(int, a.tops.split(",")):
            for m in a.modes.split(","):
                mode, w = MODES[m]
                c = replace(SearchConfig(), rerank_top=top, rerank_mode=mode, rerank_weight=w)
                t = time.time()
                s = E.DocsearchSystem(Path(a.db), embed, cfg, c, measure=False, reranker=lambda q, d: rr.score(q, d))
                summ, rows = E.run_system(s, qs)
                name = f"{a.model} top{top} {m} {a.max_chars}c"
                results[(lenient, name)] = summ
                print(E.fmt_row(name, summ), flush=True)
out = HERE / "eval" / "results" / f"{time.strftime('%Y%m%d-%H%M%S')}-rerank-{a.model}.json"
out.write_text(json.dumps({f"{'lenient' if k[0] else 'strict'}|{k[1]}": v for k, v in results.items()}, default=str))
