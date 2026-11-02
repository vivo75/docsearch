"""python eval/miss_analysis.py: where do the misses of the server config on qset2 (strict, answerable, dev+test) sit relative to the TOC / directory structure?
Uses the cached rerank scores and expansions. For every question whose gold page is not in the top 5: is the gold page reachable (rank 6-10, >10, absent), and is the
top-1 page a neighbour of it (same TOC parent / same TOC file / same directory / same ms.service)? Also: how many gold pages have a TOC position at all."""
import sys
from collections import Counter
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from compare import H, INDEXES, CONFIGS, load
from docsearch import evalrun as E
from docsearch.config import load_config
from docsearch.expand import QueryExpander
from docsearch.rerank import Reranker
from docsearch.server import _Embeddings
import sqlite3

strict, _ = load("qset2", "all"); strict = [q for q in strict if q["category"] != "unanswerable" and q["gold"]]
ex = QueryExpander("", H / "eval" / "qset2" / "expansions.json"); emb = _Embeddings(); cfg = load_config(H / "repos.toml")
memo = {t: emb(t) for q in strict for t in (q["question"], q["question"] + " " + ex.cache[q["question"]])}
db, _ = INDEXES["nomic"]
rr = Reranker("http://127.0.0.1:1", "bge-v2-m3-q8", cache=H / "eval" / "qset2" / "rerank_cache.jsonl")
sysm = E.DocsearchSystem(db, memo.__getitem__, cfg, CONFIGS["server"][0], "x", measure=False, reranker=rr.score, expander=lambda q: ex.cache[q])
con = sqlite3.connect(db)
docs = {f"{r}/{p}": (d, s, p.rsplit("/", 1)[0]) for d, r, p, s in con.execute("select doc_id, repo, path, ms_service from docs")}
tocnode = {}
for nid, pid, tp, did in con.execute("select node_id, parent_id, toc_path, doc_id from toc where doc_id is not null"):
    tocnode.setdefault(did, []).append((pid, tp))
c = Counter(); gold_in_toc = Counter(); ex_rows = []
for q in strict:
    try: res = sysm.run(q)
    except Exception: c["no-cache"] += 1; continue
    ranked = res["ranked"]; gold = set(q["gold"]); rank = next((i + 1 for i, s in enumerate(ranked) if s in gold), None)
    g = next((x for x in q["gold"] if x in docs), None)
    gold_in_toc["in TOC" if g and docs[g][0] in tocnode else "no TOC position"] += 1
    if rank and rank <= 5: c["hit@5"] += 1; continue
    c["miss@5"] += 1
    c["  gold at 6-10" if rank and rank <= 10 else "  gold beyond 10 / absent"] += 1
    t1 = ranked[0] if ranked else None
    if t1 in docs and g in docs:
        a, b = docs[t1], docs[g]
        if a[0] in tocnode and b[0] in tocnode:
            same_parent = any(x[0] == y[0] and x[0] is not None for x in tocnode[a[0]] for y in tocnode[b[0]])
            same_toc = any(x[1] == y[1] for x in tocnode[a[0]] for y in tocnode[b[0]])
        else: same_parent = same_toc = None
        c["  top1 same TOC parent" if same_parent else "  top1 same TOC file (other branch)" if same_toc else "  top1 same directory" if a[2] == b[2] else "  top1 same ms.service" if a[1] == b[1] and a[1] else "  top1 elsewhere"] += 1
    if len(ex_rows) < 12 and rank and rank > 5: ex_rows.append((q["question"][:90], rank, t1, g))
print(dict(gold_in_toc)); 
for k, v in sorted(c.items()): print(f"{k:42s} {v}")
for r in ex_rows: print(r)
