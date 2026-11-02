"""python eval/embed_slice.py {pool|nomic|qwen3|bge-m3|qwen3-4b|qwen3-8b}   (QSET=qset2 by default; QSET=v1 = the original 58 questions)
Slice test for a candidate embedding model: pool = union of nomic-vector and BM25 top-K chunks per question + all chunks of the gold pages
+ random distractors; each model embeds only the pool and ranks it by cosine for every question (page-level metrics, strict and lenient)."""
import json, random, sqlite3, sys, time
from array import array
from pathlib import Path
import numpy as np
from docsearch import evalrun as E
from docsearch.embed import Embedder, EmbedServer
from docsearch.build import embed_text
from docsearch.search import Searcher, Filters, _match, SearchConfig, parse_query
from legacy import NomicQueries as _Embeddings

H = Path(__file__).resolve().parents[1]; R = H / "eval" / "results"; DB = H / "data" / "current.db"
HF = Path("~/.cache/huggingface/hub").expanduser()
import os
QS = os.environ.get("QSET", "qset2")
SLICE = R / f"slice-{QS}"; SLICE.mkdir(exist_ok=True)   # pool and vectors are per question set: rids change when the index is updated
EOS = "<|endoftext|>"   # Qwen3-Embedding pools the last token and was trained with this appended; llama.cpp may not add it
MODELS = {  # name: (gguf, pooling, query_fn, doc_prefix)
    "qwen3": (next(HF.glob("models--Qwen--Qwen3-Embedding-0.6B-GGUF/snapshots/*/*Q8_0.gguf")), "last",
              lambda q: "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: " + q, ""),
    "qwen3-4b": (next(HF.glob("models--Qwen--Qwen3-Embedding-4B-GGUF/snapshots/*/*Q8_0.gguf"), None), "last",
                 lambda q: "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: " + q + EOS, ""),
    "qwen3-8b": (next(HF.glob("models--Qwen--Qwen3-Embedding-8B-GGUF/snapshots/*/*Q8_0.gguf"), None), "last",
                 lambda q: "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: " + q + EOS, ""),
    "bge-m3": (next(HF.glob("models--ggml-org--bge-m3-Q8_0-GGUF/snapshots/*/*.gguf")), "cls", lambda q: q, ""),
}
K, DISTRACT = int(os.environ.get("K", 20)), 2500
if QS == "v1":
    strict, lenient = E.load_questions(), E.load_questions(lenient=True)
else:
    sys.path.insert(0, str(H / "eval")); import compare
    strict, lenient = compare.load(QS, "all")


def pool():
    s = Searcher(DB, _Embeddings(), {}); f = Filters(); rids = set()
    for q in lenient:
        pq = parse_query(q["question"])
        rids |= set(s._lexical("chunks_fts", _match(pq.terms), f, SearchConfig().fields, K)) | set(s._vector(q["question"], f, K))
        for g in q["gold"]:
            repo, _, path = g.partition("/")
            rids |= {r[0] for r in s.db.execute("SELECT c.rid FROM chunks c JOIN docs d USING(doc_id) WHERE d.repo=? AND d.path=?", (repo, path))}
    allr = [r[0] for r in s.db.execute("SELECT rid FROM chunks")]
    random.Random(7).shuffle(allr); rids |= set(allr[:DISTRACT])
    (SLICE / "pool.json").write_text(json.dumps(sorted(rids))); print("pool", len(rids))


def rows(rids):
    db = sqlite3.connect(DB)
    q = ",".join(map(str, rids))
    return db.execute(f"SELECT c.rid, d.repo||'/'||d.path, d.title, c.heading_path, c.context, c.text, d.description, d.doc_id FROM chunks c JOIN docs d USING(doc_id) WHERE c.rid IN ({q}) ORDER BY c.rid").fetchall()


def toc_prefixes(doc_ids):
    """doc_id -> TOC ancestors above the page's own entry, e.g. 'Blob Storage › Data protection' (first TOC node of the page, root first)."""
    db = sqlite3.connect(DB); out = {}
    for d in doc_ids:
        row = db.execute("SELECT node_id, parent_id FROM toc WHERE doc_id=? ORDER BY node_id LIMIT 1", (d,)).fetchone()
        names = []
        while row and row[1] is not None:
            row = db.execute("SELECT node_id, parent_id, name FROM toc WHERE node_id=?", (row[1],)).fetchone()
            if row: names.append(row[2])
        out[d] = " › ".join(reversed(names))
    return out


_TOC = {}


def doc_text(r, name):
    """The text embedded for a chunk row. nomic-base = what production embeds; toc adds the TOC ancestors to the breadcrumb, desc adds the page description."""
    kind = name.split("-", 1)[1] if name.startswith("nomic-") else "base"
    if kind == "base":
        return embed_text(r[2], r[3], r[4] or "", r[5])
    if not _TOC:
        _TOC.update(toc_prefixes({x[7] for x in rows(json.loads((SLICE / "pool.json").read_text()))}))
    from docsearch.build import SEP
    bc = SEP.join(p for p in ((_TOC.get(r[7], "") if kind in ("toc", "both") else ""), r[2], r[3]) if p)
    desc = r[6] if kind in ("desc", "both") and r[6] else ""
    return "\n\n".join(p for p in (bc, desc, r[4] or "", r[5]) if p)


def evaluate(name, rids, src, D, Q):
    out = {}
    for label, qs in (("strict", strict), ("lenient", lenient)):
        rr, mrr, r5, r1 = [], 0, 0, 0; n = 0
        for q in qs:
            if not q["gold"]: continue
            sims = D @ Q[q["question"]]; order = np.argsort(-sims)
            pages = list(dict.fromkeys(src[i] for i in order[:200]))
            rank = next((i + 1 for i, p in enumerate(pages) if p in q["gold"]), None)
            n += 1; mrr += 1 / rank if rank else 0; r5 += bool(rank and rank <= 5); r1 += bool(rank and rank == 1)
        out[label] = (r1 / n, r5 / n, mrr / n)
    print(f"{name:8s} strict R@1 {out['strict'][0]:.3f} R@5 {out['strict'][1]:.3f} MRR {out['strict'][2]:.3f} | lenient R@1 {out['lenient'][0]:.3f} R@5 {out['lenient'][1]:.3f} MRR {out['lenient'][2]:.3f}")


def main(name):
    if name == "pool": return pool()
    rids = json.loads((SLICE / "pool.json").read_text()); data = rows(rids); src = [r[1] for r in data]
    qtexts = [q["question"] for q in lenient]
    if name == "nomic":
        db = sqlite3.connect(DB); db.enable_load_extension(True)
        import sqlite_vec; sqlite_vec.load(db)
        vec = dict(db.execute(f"SELECT rowid, embedding FROM chunks_vec WHERE rowid IN ({','.join(map(str, rids))})").fetchall())
        D = np.array([np.frombuffer(vec[r[0]], dtype=np.float32) for r in data])
        emb = _Embeddings(); Q = {t: np.frombuffer(emb(t), dtype=np.float32) for t in qtexts}
        return evaluate(name, rids, src, D, Q)
    if name.startswith("nomic-"):      # nomic with a different document text: nomic-base | nomic-toc | nomic-desc | nomic-both (see doc_text)
        from docsearch.embed import NOMIC, NOMIC_DOC_PREFIX, NOMIC_QUERY_PREFIX
        MODELS[name] = (NOMIC, "mean", lambda q: NOMIC_QUERY_PREFIX + q, NOMIC_DOC_PREFIX)
    gguf, pooling, qfn, dp = MODELS[name]
    class Srv(EmbedServer):
        def _cmd(self, exe):
            c = super()._cmd(exe); c[c.index("--pooling") + 1] = pooling; c[c.index("-b") + 1] = "4096"; c[c.index("-ub") + 1] = "4096"; return c
    t0 = time.time()
    with Srv(gguf, "Vulkan0", 8095, ctx=8192, parallel=2) as srv:
        e = Embedder(srv.url, workers=1, batch_tokens=3500, batch_items=16)
        cache = SLICE / f"{name}.npy"
        if cache.exists(): D = np.load(cache)
        else:
            texts = [doc_text(r, name) + (EOS if name in ("qwen3-4b", "qwen3-8b") else "") for r in data]
            vecs = []
            for i in range(0, len(texts), 1000):
                vecs += e.embed(texts[i:i + 1000], dp); print(f"  {name}: {len(vecs)}/{len(texts)} {time.time()-t0:.0f}s", flush=True)
            D = np.array([np.frombuffer(v, dtype=np.float32) for v in vecs]); np.save(cache, D)
        Q = {t: np.frombuffer(e.embed([qfn(t)], "")[0], dtype=np.float32) for t in qtexts}
    D = D / np.linalg.norm(D, axis=1, keepdims=True); Q = {k: v / np.linalg.norm(v) for k, v in Q.items()}
    print(f"  {name}: {time.time()-t0:.0f}s, dims {D.shape[1]}")
    evaluate(name, rids, src, D, Q)


main(sys.argv[1])
