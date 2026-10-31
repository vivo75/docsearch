"""python eval/bge_full.py check|embed
Full-corpus bge-m3 experiment index: copies data/current.db -> data/exp-bge-m3.db (NOT index-*.db, so swap() never prunes it),
replaces chunks_vec with 1024-d bge-m3 vectors (cls pooling, no prefixes), resumable; restarts the server every 15k chunks.
`check` embeds 200 slice-pool chunks through the same path and compares them with eval/results/slice_bge-m3.npy."""
import json, os, shutil, sqlite3, sys, time
from pathlib import Path
import numpy as np
from docsearch import store
from docsearch.build import embed_text
from docsearch.embed import hf_file, Embedder, EmbedServer

H = Path(__file__).resolve().parents[1]; R = H / "eval" / "results"
SRC, DST = H / "data" / "current.db", H / "data" / "exp-bge-m3.db"
GGUF = hf_file("ggml-org/bge-m3-Q8_0-GGUF", "bge-m3-q8_0.gguf")
DEVICE = os.environ.get("BGE_DEVICE", "ROCm0")   # 7900 XTX: ROCm matches the RX 6600 slice vectors best (cos .9998) and is fastest
PORT = 8095          # dedicated: EmbedServer.__enter__ accepts ANY healthy server on its port (nomic lives on 8099/8098)
GROUP, RESTART_EVERY = 1500, 10


class Srv(EmbedServer):
    def __init__(self):
        super().__init__(GGUF, DEVICE, PORT, ctx=8192, parallel=2)

    def _cmd(self, exe):
        c = super()._cmd(exe); c[c.index("--pooling") + 1] = "cls"; c[c.index("-b") + 1] = "4096"; c[c.index("-ub") + 1] = "4096"; return c

    def __enter__(self):
        if self._up(): raise RuntimeError(f"port {PORT} already answers: refusing to reuse an unknown server")
        return super().__enter__()


def mk_embedder(srv): return Embedder(srv.url, workers=1, batch_tokens=3500, batch_items=16)
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)


def check():
    pool = json.loads((R / "slice_pool.json").read_text()); ref = np.load(R / "slice_bge-m3.npy")
    pick = list(range(0, len(pool), len(pool) // 200))[:200]
    db = sqlite3.connect(SRC); q = ",".join(str(pool[i]) for i in pick)
    rows = {r[0]: r for r in db.execute(f"SELECT c.rid, d.title, c.heading_path, c.context, c.text FROM chunks c JOIN docs d USING(doc_id) WHERE c.rid IN ({q})")}
    rids = [pool[i] for i in pick if pool[i] in rows]
    with Srv() as srv:
        v = mk_embedder(srv).embed([embed_text(*rows[r][1:]) for r in rids], "")
    D = np.array([np.frombuffer(x, dtype=np.float32) for x in v]); D /= np.linalg.norm(D, axis=1, keepdims=True)
    idx = [pool.index(r) for r in rids]; Rf = ref[idx]; Rf = Rf / np.linalg.norm(Rf, axis=1, keepdims=True)
    cos = (D * Rf).sum(1); print(f"{len(rids)} chunks, dims {D.shape[1]}, cosine vs slice: min {cos.min():.4f} mean {cos.mean():.4f}")


def embed():
    if not DST.exists():
        shutil.copy(SRC.resolve(), DST); log("copied", SRC.resolve().name)
        db = store.connect(DST); db.execute("DROP TABLE chunks_vec")
        db.execute("CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding float[1024] distance_metric=cosine)")
        store.set_meta(db, model="bge-m3-Q8_0", dims=1024); db.commit()
    else:
        db = store.connect(DST)
    db.execute("PRAGMA synchronous=OFF")
    todo = db.execute("SELECT c.rid, c.token_count, d.title, c.heading_path, c.context, c.text FROM chunks c JOIN docs d USING(doc_id) "
                      "WHERE NOT EXISTS (SELECT 1 FROM chunks_vec v WHERE v.rowid = c.rid) ORDER BY c.rid").fetchall()
    log(f"{len(todo)} chunks to embed")
    t0, done = time.time(), 0
    srv = Srv(); srv.__enter__(); emb = mk_embedder(srv)
    try:
        for n, i in enumerate(range(0, len(todo), GROUP)):
            if n and n % RESTART_EVERY == 0:
                srv.restart(); emb = mk_embedder(srv); log("restarted server")
            part = todo[i:i + GROUP]
            vecs = emb.embed([embed_text(*r[2:]) for r in part], "", [r[1] + 20 for r in part])
            db.executemany("INSERT INTO chunks_vec(rowid, embedding) VALUES (?,?)", [(r[0], v) for r, v in zip(part, vecs)]); db.commit()
            done += len(part); rate = done / (time.time() - t0)
            log(f"embedded {done}/{len(todo)}  {rate:.1f} chunks/s  eta {(len(todo) - done) / rate / 60:.0f} min")
    finally:
        srv.__exit__()
    log("health:", store.health(db) or "ok"); db.execute("ANALYZE"); db.commit(); log("done")


{"check": check, "embed": embed}[sys.argv[1]]()
