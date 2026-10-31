"""python eval/expand_eval.py  -> generates cached query expansions with the local LLM, then compares configurations."""
import json
import time
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
from docsearch import evalrun as E
from docsearch.config import load_config
from docsearch.expand import ExpandServer, QueryExpander
from docsearch.rerank import Reranker, RerankServer
from docsearch.search import SearchConfig
from docsearch.server import _Embeddings

CACHE = HERE / "eval" / "results" / "expansions.json"
strict, lenient = E.load_questions(), E.load_questions(lenient=True)
t0 = time.time()
ex = QueryExpander("", CACHE)                    # all expansions are cached; no LLM needed
missing = [q["question"] for q in strict if q["question"] not in ex.cache]
if missing:
    with ExpandServer() as srv:
        ex.url = srv.url
        for q in missing: ex(q)
for q in strict[:0]: pass
for question in ["How do I give someone read-only access to a resource group?", "Create a diagnostic setting for Blob storage using PowerShell",
                 "How do I back up virtual machines in Azure and what gets backed up?", "Should I use a VPN gateway or ExpressRoute to link my datacenter to Azure?"]:
    print(f"  {question[:62]:62s} -> {ex.cache[question]}")

cfg = load_config(HERE / "repos.toml")
emb, memo = _Embeddings(), {}
embed = lambda q: memo.setdefault(q, emb(q))
expander = lambda q: ex.cache[q]
D = SearchConfig()
R = replace(D, rerank_top=10, rerank_mode="rrf", rerank_weight=1.0)
CONFIGS = {
    "baseline": D,
    "expand lexical (w=1)": replace(D, expand_lex=1.0),
    "expand vector (w=1)": replace(D, expand_vec=1.0),
    "expand both (w=1,1)": replace(D, expand_lex=1.0, expand_vec=1.0),
    "expand both (w=.5,.5)": replace(D, expand_lex=0.5, expand_vec=0.5),
    "baseline + rerank": R,
    "expand both (1,1) + rerank": replace(R, expand_lex=1.0, expand_vec=1.0),
    "expand both (.5,.5) + rerank": replace(R, expand_lex=0.5, expand_vec=0.5),
    "expand vec (1) + rerank": replace(R, expand_vec=1.0),
    "expand vec (.5) + rerank": replace(R, expand_vec=0.5),
    "expand vec (2) + rerank": replace(R, expand_vec=2.0),
    "expand vec (2)": replace(D, expand_vec=2.0),
    "expand vec (.5)": replace(D, expand_vec=0.5),
}
with RerankServer("bge-v2-m3-q8") as rs:         # phase 2: embedding + reranker servers
    rr = Reranker(rs.url, "bge-v2-m3-q8", cache=HERE / "eval" / "results" / "rerank_cache.jsonl")
    for qs, label in ((strict, "STRICT"), (lenient, "LENIENT")):
        for q in qs: embed(q["question"]); embed(q["question"] + " " + ex.cache[q["question"]])
        print(f"\n== {label} ==\n{E.HEADER}")
        for name, c in CONFIGS.items():
            s = E.DocsearchSystem(HERE / "data" / "current.db", embed, cfg, c, name, measure=False,
                                  reranker=lambda q, d: rr.score(q, d), expander=expander)
            summ, rows = E.run_system(s, qs)
            print(E.fmt_row(name, summ), flush=True)
