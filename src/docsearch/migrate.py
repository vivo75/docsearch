"""Upgrade an existing index to the current schema without re-embedding."""
from __future__ import annotations

import shutil
from pathlib import Path

from . import store
from .build import log
from .config import load_config
from .toc import build_toc


def migrate(cfg_path: str, out_dir: Path) -> Path:
    cfg = load_config(cfg_path)
    link = out_dir / "current.db"
    src = link.resolve()
    dst = out_dir / f"index-{store.stamp()}.db"
    shutil.copyfile(src, dst)                     # never edit the live index in place
    db = store.connect(dst)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='toc'").fetchone():
        db.executescript(store.TOC_SCHEMA)
    rows = db.execute("SELECT doc_id, ms_date FROM docs WHERE ms_date IS NOT NULL").fetchall()
    db.executemany("UPDATE docs SET ms_date=? WHERE doc_id=?", [(store.normalize_date(d), i) for i, d in rows])
    n = build_toc(db, cfg)
    store.set_meta(db, schema_version=store.SCHEMA_VERSION, migrated_from=src.name)
    problems = store.health(db)
    log(f"toc nodes: {n}; dates normalized: {len(rows)}; health: {problems or 'ok'}")
    db.close()
    if problems:
        raise SystemExit(f"migration NOT published: {problems}")
    store.swap(dst, link)
    log(f"published {dst.name}")
    return dst
