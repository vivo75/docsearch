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
    rids, rows = [], []
    for rid, blob in db.execute("SELECT rowid, embedding FROM chunks_vec"):
        rids.append(rid); rows.append(blob)
    db.close()
    if not rids:
        return 0
    m = np.frombuffer(b"".join(rows), dtype=np.float32).reshape(len(rids), -1)
    m = m / np.maximum(np.linalg.norm(m, axis=1, keepdims=True), 1e-12)          # dot product == cosine similarity
    mp, rp = paths(db_path)
    for target, arr in ((mp, m.astype(np.float32)), (rp, np.array(rids, dtype=np.int64))):
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "wb") as f:
            np.save(f, arr)
        os.replace(tmp, target)
    return len(rids)


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


def load(db_path, db=None) -> VecMatrix | None:
    if os.environ.get("DOCSEARCH_VECMAT", "").lower() == "off":
        return None
    mp, rp = paths(db_path)
    if not (mp.exists() and rp.exists()):
        return None
    try:
        rids = np.load(rp)
        m = np.load(mp, mmap_mode="r")
        db = db or store.connect(db_path, readonly=True)
        n = db.execute("SELECT count(*) FROM chunks_vec").fetchone()[0]
        if len(rids) != n or m.shape[0] != n:
            return None
        return VecMatrix(m, rids)
    except (OSError, ValueError):
        return None
