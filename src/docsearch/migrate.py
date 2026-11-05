"""Upgrade an existing index to the current schema without re-embedding."""
from __future__ import annotations

import shutil
from pathlib import Path

from . import store
from .build import log, publish_index
from .config import load_config
from .docfxmeta import file_metadata
from .toc import build_toc


def migrate(cfg_path: str, out_dir: Path) -> Path:
    cfg = load_config(cfg_path)
    link = out_dir / "current.db"
    src = link.resolve()
    part = out_dir / f"index-{store.stamp()}.partial"      # a failed migration must not look like a published index
    shutil.copyfile(src, part)                     # never edit the live index in place
    db = store.connect(part)
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='toc'").fetchone():
        db.executescript(store.TOC_SCHEMA)
    rows = db.execute("SELECT doc_id, ms_date FROM docs WHERE ms_date IS NOT NULL").fetchall()
    db.executemany("UPDATE docs SET ms_date=? WHERE doc_id=?", [(store.normalize_date(d), i) for i, d in rows])
    filled = 0
    for doc_id, repo, path, _ in db.execute("SELECT doc_id, repo, path, ms_service FROM docs WHERE ms_service IS NULL OR ms_service = ''").fetchall():
        r = next((x for x in cfg.repos if x.name == repo), None)
        if r and (v := file_metadata(r.path, path).get("ms.service")):
            db.execute("UPDATE docs SET ms_service=? WHERE doc_id=?", (v, doc_id)); filled += 1
    log(f"ms.service filled from docfx.json: {filled}")
    n = build_toc(db, cfg)
    store.set_meta(db, schema_version=store.SCHEMA_VERSION, migrated_from=src.name)
    problems = store.health(db)
    log(f"toc nodes: {n}; dates normalized: {len(rows)}; health: {problems or 'ok'}")
    db.execute("PRAGMA journal_mode=DELETE")
    db.close()
    if problems:
        raise SystemExit(f"migration NOT published: {problems} (kept as {part.name})")
    dst = part.with_suffix(".db")
    part.rename(dst)
    publish_index(dst, link)
    log(f"published {dst.name}")
    return dst
