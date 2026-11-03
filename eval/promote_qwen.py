"""python eval/promote_qwen.py [--swap]   Promote data/exp-qwen3-4b.db (eval/qwen_full.py embed) to a live index.
Copies it to data/index-<stamp>.db, rewrites chunks.content_hash for the production MODEL_ID (the experiment kept the nomic hashes, so an
update would re-embed every touched page's unchanged chunks), checks health and canaries, and with --swap repoints current.db."""
import shutil, sys, time
from pathlib import Path
from docsearch import store
from docsearch.build import embed_text, log
from docsearch.canary import run_canaries
from docsearch.embed import MODEL_ID
import hashlib

H = Path(__file__).resolve().parents[1]; SRC = H / "data" / "exp-qwen3-4b.db"
dst = H / "data" / f"index-{store.stamp()}.partial"
shutil.copyfile(SRC, dst); log("copied", SRC.name)
db = store.connect(dst); db.execute("PRAGMA synchronous=OFF")
rows = db.execute("SELECT c.rid, d.title, c.heading_path, c.context, c.text FROM chunks c JOIN docs d USING(doc_id)").fetchall()
db.executemany("UPDATE chunks SET content_hash=? WHERE rid=?",
               [(hashlib.sha256((embed_text(t, hp, cx or "", tx) + "\0" + MODEL_ID).encode()).hexdigest(), rid) for rid, t, hp, cx, tx in rows])
store.set_meta(db, model=MODEL_ID, dims=store.DIMS, promoted_from=SRC.name, built_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
db.commit()
problems = store.health(db); log("health:", problems or "ok")
db.execute("ANALYZE"); db.commit(); db.execute("PRAGMA journal_mode=DELETE"); db.close()
if problems:
    sys.exit(1)
final = dst.with_suffix(".db"); dst.rename(final)
from docsearch import vecmat; log("vecmat:", vecmat.build(final))
problems = run_canaries(final); log("canary:", problems or "ok")
if problems:
    sys.exit(f"not swapped; candidate kept as {final.name}")
if "--swap" in sys.argv:
    store.swap(final, H / "data" / "current.db"); log("current.db ->", final.name)
else:
    log("candidate", final.name, "(run with --swap to publish)")
