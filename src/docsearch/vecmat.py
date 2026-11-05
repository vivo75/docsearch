"""Exact vector search over an in-memory (memory-mapped) matrix instead of sqlite-vec's single-threaded scan.

For an index `index-STAMP.db` the cache is `index-STAMP.db.vec.npy` (L2-normalised float32 rows) and `index-STAMP.db.vec.rids.npy`
(the chunks_vec rowids). Indexes are immutable once published, so the cache is keyed by file name; `load` still checks the row count
and returns None (caller falls back to sqlite-vec) when the cache is missing, stale or disabled (DOCSEARCH_VECMAT=off).
Measured on 300k x 2560: 124 ms per query against 1600 ms for sqlite-vec, identical top-50.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from . import store


def paths(db_path) -> tuple[Path, Path]:
    p = str(db_path)
    return Path(p + ".vec.npy"), Path(p + ".vec.rids.npy")


def remove(db_path) -> None:
    for p in paths(db_path):
        p.unlink(missing_ok=True)


def build(db_path) -> int:
    """Write the cache for `db_path` (atomic: temp files, then rename). Returns the number of vectors."""
    db = store.connect(db_path, readonly=True)
    n = db.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
    if not n:
        db.close()
        return 0
    m = rids = None
    for i, (rid, blob) in enumerate(db.execute("SELECT rowid, embedding FROM chunks_vec")):     # one preallocated matrix, normalised row by row
        v = np.frombuffer(blob, dtype=np.float32)
        if m is None:
            m, rids = np.empty((n, v.shape[0]), dtype=np.float32), np.empty(n, dtype=np.int64)
        m[i] = v / max(float(np.linalg.norm(v)), 1e-12)            # dot product == cosine similarity
        rids[i] = rid
    db.close()
    mp, rp = paths(db_path)
    for target, arr in ((mp, m), (rp, rids)):
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "wb") as f:
            np.save(f, arr)
        os.replace(tmp, target)
    return n


class VecMatrix:
    def __init__(self, matrix: np.ndarray, rids: np.ndarray):
        self.m, self.rids = matrix, rids

    def top(self, query: bytes, k: int, allowed: set[int] | None = None) -> list[int]:
        """Rowids of the k nearest chunks by cosine, best first; `allowed` restricts the candidates."""
        q = np.frombuffer(query, dtype=np.float32)
        if q.shape[0] != self.m.shape[1]:
            raise ValueError(f"query has {q.shape[0]} dimensions, index has {self.m.shape[1]}")
        s = self.m @ (q / max(float(np.linalg.norm(q)), 1e-12))
        if allowed is not None:
            s = np.where(np.isin(self.rids, np.fromiter(allowed, dtype=np.int64, count=len(allowed))), s, -np.inf)
        k = min(k, int(np.isfinite(s).sum()))
        if k <= 0:
            return []
        i = np.argpartition(-s, k - 1)[:k]
        return [int(r) for r in self.rids[i[np.argsort(-s[i], kind="stable")]]]


def load_why(db_path, db=None) -> tuple[VecMatrix | None, str | None]:
    """(matrix, None) when the cache is usable, else (None, reason). Only the sizes are compared here (cheap, done at every index open);
    `check` compares the rowids themselves."""
    if os.environ.get("DOCSEARCH_VECMAT", "").lower() == "off":
        return None, "disabled (DOCSEARCH_VECMAT=off)"
    mp, rp = paths(db_path)
    if not (mp.exists() and rp.exists()):
        return None, f"cache file missing ({mp.name} / {rp.name}); build it with `docsearch vecmat`"
    try:
        rids = np.load(rp)
        m = np.load(mp, mmap_mode="r")
        db = db or store.connect(db_path, readonly=True)
        n = db.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
        if len(rids) != n or m.shape[0] != n:
            return None, f"stale: matrix has {m.shape[0]} rows, rids {len(rids)}, chunks_vec {n}; rebuild with `docsearch vecmat`"
        return VecMatrix(m, rids), None
    except (OSError, ValueError) as e:
        return None, f"unreadable ({type(e).__name__}: {e})"


def load(db_path, db=None) -> VecMatrix | None:
    return load_why(db_path, db)[0]


def check(db_path, sample: int = 20, seed: int = 1) -> dict:
    """Full coherence check of the cache against the index: same sizes, the SAME rowid set (no duplicates), and `sample` random rows
    compared with the embeddings in the database (after normalisation). `problems` is empty when everything agrees."""
    import random
    mp, rp = paths(db_path)
    out: dict = {"index": Path(db_path).name, "matrix_file": mp.name, "problems": []}
    pr = out["problems"]
    if not (mp.exists() and rp.exists()):
        pr.append("cache file missing")
        return out
    m, rids = np.load(mp, mmap_mode="r"), np.load(rp)
    db = store.connect(db_path, readonly=True)
    ids = np.fromiter((r[0] for r in db.execute("SELECT rowid FROM chunks_vec")), dtype=np.int64)
    out.update(matrix_rows=int(m.shape[0]), dims=int(m.shape[1]) if m.ndim == 2 else None, rids=int(len(rids)), chunks_vec=int(len(ids)),
               matrix_bytes=int(mp.stat().st_size))
    if not (m.shape[0] == len(rids) == len(ids)):
        pr.append(f"sizes differ: matrix {m.shape[0]}, rids {len(rids)}, chunks_vec {len(ids)}")
    if len(set(rids.tolist())) != len(rids):
        pr.append("duplicate rowids in the cache")
    if set(rids.tolist()) != set(ids.tolist()):
        pr.append(f"rowid sets differ: {len(set(rids.tolist()) - set(ids.tolist()))} only in the cache, {len(set(ids.tolist()) - set(rids.tolist()))} only in the index")
    if not np.isfinite(np.asarray(m[:: max(1, len(rids) // 2000)])).all():
        pr.append("non-finite values in the matrix")
    worst = 0.0
    rng = random.Random(seed)
    for i in rng.sample(range(len(rids)), min(sample, len(rids))) if len(rids) else []:
        row = db.execute("SELECT embedding FROM chunks_vec WHERE rowid = ?", (int(rids[i]),)).fetchone()
        if row is None:
            pr.append(f"rowid {int(rids[i])} is not in chunks_vec")
            continue
        v = np.frombuffer(row[0], dtype=np.float32)
        d = float(np.abs(m[i] - v / max(float(np.linalg.norm(v)), 1e-12)).max())
        worst = max(worst, d)
    out["sample_max_abs_diff"] = worst
    if worst > 1e-5:
        pr.append(f"sampled rows differ from the database embeddings (max abs diff {worst:.2e})")
    db.close()
    return out
