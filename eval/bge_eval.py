"""python eval/bge_eval.py  -> same harness, same questions/expansions/rerank cache, nomic (current.db) vs bge-m3 (exp-bge-m3.db).
Configs are fixed in advance (no re-tuning of weights for bge-m3). Prints strict + lenient tables, canary pass, per-question changes."""
import json, time, tomllib
from dataclasses import replace
from pathlib import Path
from docsearch import evalrun as E
from docsearch.config import load_config
from docsearch.embed import Embedder, EmbedServer
from docsearch.expand import QueryExpander
from docsearch.rerank import Reranker, RerankServer
from docsearch.search import SearchConfig
from docsearch.server import _Embeddings, SERVER_CONFIG

H = Path(__file__).resolve().parents[1]; R = H / "eval" / "results"
GGUF = next((Path("~/.cache/huggingface/hub").expanduser()).glob("models--ggml-org--bge-m3-Q8_0-GGUF/snapshots/*/*.gguf"))
DBS = {"nomic": H / "data" / "current.db", "bge-m3": H / "data" / "exp-bge-m3.db"}
strict, lenient = E.load_questions(), E.load_questions(lenient=True)
ex = QueryExpander("", R / "expansions.json"); cfg = load_config(H / "repos.toml")
canary = tomllib.loads((H / "canaries.toml").read_text())["canary"]["ids"]
D = SearchConfig(); RR = SERVER_CONFIG
CONFIGS = {"vector-only": replace(D, bm25=0, phrase=0, ident=0), "hybrid": D, "hybrid + rerank": RR,
           "hybrid + expand_vec": replace(D, expand_vec=1.0), "SERVER (expand_vec + rerank)": replace(RR, expand_vec=1.0)}


class Bge(EmbedServer):
    def __init__(self): super().__init__(GGUF, "Vulkan0", 8095, ctx=4096, parallel=2)
    def _cmd(self, exe):
        c = super()._cmd(exe); c[c.index("--pooling") + 1] = "cls"; c[c.index("-b") + 1] = "4096"; c[c.index("-ub") + 1] = "4096"; return c
    def __enter__(self):
        if self._up(): raise RuntimeError("port 8095 already answers")
        return super().__enter__()


texts = sorted({t for q in lenient for t in (q["question"], q["question"] + " " + ex.cache[q["question"]])})
memo = {"nomic": {}, "bge-m3": {}}; embed_ms = {}
nomic = _Embeddings()
t = time.perf_counter()
for s in texts: memo["nomic"][s] = nomic(s)
embed_ms["nomic"] = (time.perf_counter() - t) / len(texts) * 1000
with Bge() as srv:                       # distinct short-lived server: bge-m3 loaded only for query embedding
    e = Embedder(srv.url, workers=1); t = time.perf_counter()
    for s in texts: memo["bge-m3"][s] = e.embed([s], "")[0]
    embed_ms["bge-m3"] = (time.perf_counter() - t) / len(texts) * 1000
print({k: f"{v:.0f} ms/query embed (warm, uncached)" for k, v in embed_ms.items()})

results = {}
with RerankServer("bge-v2-m3-q8") as rs:
    rr = Reranker(rs.url, "bge-v2-m3-q8", cache=R / "rerank_cache.jsonl")
    for label, qs in (("STRICT", strict), ("LENIENT", lenient)):
        print(f"\n== {label} ==\n{E.HEADER}")
        for model, db in DBS.items():
            for name, c in CONFIGS.items():
                s = E.DocsearchSystem(db, memo[model].__getitem__, cfg, c, f"{model}: {name}", measure=False,
                                      reranker=(lambda q, d: rr.score(q, d)), expander=lambda q: ex.cache[q])
                summ, rows = E.run_system(s, qs)
                results[(label, model, name)] = (summ, rows); print(E.fmt_row(f"{model}: {name}", summ), flush=True)

print("\nCanary (lenient, top-5) under SERVER config:")
for model in DBS:
    rows = results[("LENIENT", model, "SERVER (expand_vec + rerank)")][1]
    print(f"  {model}: {sum(r['r5'] for r in rows if r['id'] in canary)}/{len(canary)}")
print("\nPer-question changes under SERVER config (rank nomic -> bge-m3; strict | lenient):")
for label in ("STRICT", "LENIENT"):
    a = {r["id"]: r["rank"] for r in results[(label, "nomic", "SERVER (expand_vec + rerank)")][1]}
    b = {r["id"]: r["rank"] for r in results[(label, "bge-m3", "SERVER (expand_vec + rerank)")][1]}
    print(f" {label}:", ", ".join(f"{i} {a[i]}->{b[i]}" for i in a if a[i] != b[i]) or "none")
(R / f"{time.strftime('%Y%m%d-%H%M%S')}-bge-vs-nomic.json").write_text(json.dumps({"|".join(k): v[0] for k, v in results.items()}, default=str))
