"""python eval/qwen_full.py check|embed   (QWEN_DEVICE=ROCm0|Vulkan0, default ROCm0; QWEN_SIZE=4b|8b, default 4b)
Full-corpus Qwen3-Embedding experiment index: copies data/current.db -> data/exp-qwen3-<size>.db (NOT index-*.db, so swap() never prunes it),
replaces chunks_vec with Qwen3-Embedding vectors (last-token pooling, `<|endoftext|>` appended to documents), resumable.
`check` embeds 200 slice-pool chunks on the chosen device, compares them with eval/results/slice-qset2/qwen3-<size>.npy and prints the speed."""
import json, os, shutil, sqlite3, sys, time
from pathlib import Path
import numpy as np
from docsearch import store
from docsearch.build import embed_text
from docsearch.embed import QWEN_EOS as EOS, Embedder, QwenServer

H = Path(__file__).resolve().parents[1]; R = H / "eval" / "results" / "slice-qset2"
SIZE = os.environ.get("QWEN_SIZE", "4b"); DEV = os.environ.get("QWEN_DEVICE", "ROCm0")
SRC, DST = H / "data" / "current.db", H / "data" / f"exp-qwen3-{SIZE}.db"
DIMS = {"4b": 2560, "8b": 4096}[SIZE]
GROUP, RESTART_EVERY = 1000, 15


def Srv(): return QwenServer(SIZE, DEV)


def mk(srv): return Embedder(srv.url, workers=1, batch_tokens=3500, batch_items=16)
def log(*a): print(time.strftime("%H:%M:%S"), *a, flush=True)
def text(r): return embed_text(*r) + EOS


def check():
    pool = json.loads((R / "pool.json").read_text()); ref = np.load(R / f"qwen3-{SIZE}.npy")
    pick = list(range(0, len(pool), len(pool) // 200))[:200]
    db = sqlite3.connect(SRC); q = ",".join(str(pool[i]) for i in pick)
    rows = {r[0]: r for r in db.execute(f"SELECT c.rid, d.title, c.heading_path, c.context, c.text FROM chunks c JOIN docs d USING(doc_id) WHERE c.rid IN ({q})")}
    rids = [pool[i] for i in pick if pool[i] in rows]
    with Srv() as srv:
        t = time.time(); v = mk(srv).embed([text(rows[r][1:]) for r in rids], ""); dt = time.time() - t
    D = np.array([np.frombuffer(x, dtype=np.float32) for x in v]); D /= np.linalg.norm(D, axis=1, keepdims=True)
    Rf = ref[[pool.index(r) for r in rids]]; Rf = Rf / np.linalg.norm(Rf, axis=1, keepdims=True)
    cos = (D * Rf).sum(1); print(f"{DEV}: {len(rids)} chunks in {dt:.1f}s = {len(rids)/dt:.1f}/s, dims {D.shape[1]}, cosine vs slice: min {cos.min():.4f} mean {cos.mean():.4f}")


def embed():
    if not DST.exists():
        shutil.copy(SRC.resolve(), DST); log("copied", SRC.resolve().name)
        db = store.connect(DST); db.execute("DROP TABLE chunks_vec")
        db.execute(f"CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding float[{DIMS}] distance_metric=cosine)")
        store.set_meta(db, model=f"Qwen3-Embedding-{SIZE.upper()}-Q8_0", dims=DIMS); db.commit()
    else:
        db = store.connect(DST)
    db.execute("PRAGMA synchronous=OFF")
    todo = db.execute("SELECT c.rid, c.token_count, d.title, c.heading_path, c.context, c.text FROM chunks c JOIN docs d USING(doc_id) "
                      "WHERE NOT EXISTS (SELECT 1 FROM chunks_vec v WHERE v.rowid = c.rid) ORDER BY c.rid").fetchall()
    log(f"{len(todo)} chunks to embed on {DEV}")
    t0, done = time.time(), 0
    srv = Srv(); srv.__enter__(); emb = mk(srv)
    try:
        for n, i in enumerate(range(0, len(todo), GROUP)):
            if n and n % RESTART_EVERY == 0:
                srv.restart(); emb = mk(srv); log("restarted server")
            part = todo[i:i + GROUP]
            vecs = emb.embed([text(r[2:]) for r in part], "", [r[1] + 20 for r in part])
            db.executemany("INSERT INTO chunks_vec(rowid, embedding) VALUES (?,?)", [(r[0], v) for r, v in zip(part, vecs)]); db.commit()
            done += len(part); rate = done / (time.time() - t0)
            log(f"embedded {done}/{len(todo)}  {rate:.1f} chunks/s  eta {(len(todo) - done) / rate / 60:.0f} min")
    finally:
        srv.__exit__()
    log("health:", store.health(db) or "ok"); db.execute("ANALYZE"); db.commit(); log("done")


{"check": check, "embed": embed}[sys.argv[1]]()
