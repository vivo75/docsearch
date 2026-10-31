"""SQLite index: schema, writers, health checks and atomic swap (design 6.1, 9)."""
from __future__ import annotations

import os
import re
import sqlite3
import time
from pathlib import Path

import sqlite_vec

SCHEMA_VERSION = "1"
DIMS = 768

SCHEMA = f"""
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE docs (
  doc_id INTEGER PRIMARY KEY,
  repo TEXT NOT NULL, path TEXT NOT NULL, url TEXT, title TEXT, description TEXT,
  ms_service TEXT, ms_subservice TEXT, ms_topic TEXT, ms_date TEXT,
  last_commit_date TEXT, blob_hash TEXT, flags TEXT,
  UNIQUE(repo, path)
);
CREATE TABLE chunks (
  rid INTEGER PRIMARY KEY,
  chunk_id TEXT NOT NULL UNIQUE,
  doc_id INTEGER NOT NULL REFERENCES docs(doc_id),
  heading_path TEXT, anchor TEXT,
  variant_tab TEXT, variant_pivot TEXT, variant_moniker TEXT,
  parent_id TEXT, prev_id TEXT, next_id TEXT,
  text TEXT NOT NULL, context TEXT, token_count INTEGER,
  content_hash TEXT NOT NULL                -- sha256(embed_text + model id)
);
CREATE INDEX chunks_doc ON chunks(doc_id);
CREATE INDEX chunks_pivot ON chunks(variant_pivot);
CREATE INDEX docs_service ON docs(ms_service);
CREATE INDEX docs_topic ON docs(ms_topic);
CREATE INDEX docs_repo ON docs(repo);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  title, description, heading_path, text,
  content='', contentless_delete=1, tokenize='porter unicode61 remove_diacritics 2');
-- identifiers (az vm create, --resource-group, Microsoft.Storage/accounts): '-_./' are token chars
CREATE VIRTUAL TABLE chunks_ident USING fts5(
  tokens, content='', contentless_delete=1, tokenize="unicode61 tokenchars '-_./'");
CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding float[{DIMS}] distance_metric=cosine);
CREATE TABLE deps (doc_id INTEGER NOT NULL, dep_path TEXT NOT NULL);
CREATE INDEX deps_path ON deps(dep_path);
CREATE TABLE redirects (old_url TEXT PRIMARY KEY, new_url TEXT NOT NULL);
CREATE TABLE links (src_doc_id INTEGER NOT NULL, dst_url TEXT NOT NULL);
"""

TOC_SCHEMA = """
CREATE TABLE toc (
  node_id INTEGER PRIMARY KEY, parent_id INTEGER, ord INTEGER,
  repo TEXT NOT NULL, toc_path TEXT NOT NULL, name TEXT, href TEXT,
  doc_id INTEGER, url TEXT
);
CREATE INDEX toc_parent ON toc(parent_id);
CREATE INDEX toc_file ON toc(repo, toc_path);
"""

_IDENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-/]*[A-Za-z0-9_]")


def ident_tokens(*parts: str) -> str:
    """Tokens that carry one of `-_./` (CLI flags, resource types, config keys, file names)."""
    seen: dict[str, None] = {}
    for p in parts:
        for t in _IDENT.findall(p or ""):
            if len(t) >= 3 and any(c in t for c in "-_./"):
                seen[t.lower()] = None
    return " ".join(seen)


def normalize_date(v: object) -> str | None:
    """Learn's ms.date is M/D/YYYY (or an ISO date); return YYYY-MM-DD so it sorts and filters."""
    if v is None:
        return None
    t = str(v).strip()
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t):
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    if m := re.match(r"(\d{4})-(\d{2})-(\d{2})", t):
        return m.group(0)
    return None


def connect(path: str | Path, readonly: bool = False, shared: bool = False) -> sqlite3.Connection:
    """`shared=True` lets other threads use the connection (callers must serialize access)."""
    uri = f"file:{path}?mode={'ro' if readonly else 'rwc'}"
    db = sqlite3.connect(uri, uri=True, check_same_thread=not shared)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def create(path: str | Path) -> sqlite3.Connection:
    db = connect(path)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=OFF")
    db.executescript(SCHEMA + TOC_SCHEMA)
    return db


def set_meta(db: sqlite3.Connection, **kv: object) -> None:
    db.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in kv.items()])


def get_meta(db: sqlite3.Connection) -> dict[str, str]:
    return dict(db.execute("SELECT key, value FROM meta"))


def health(db: sqlite3.Connection) -> list[str]:
    """Return a list of problems (empty = healthy). FTS <-> vec <-> chunks must agree."""
    q = lambda sql: db.execute(sql).fetchone()[0]
    problems = []
    n = q("SELECT count(*) FROM chunks")
    nv = q("SELECT count(*) FROM chunks_vec")
    nf = q("SELECT count(*) FROM chunks_fts_docsize")
    ni = q("SELECT count(*) FROM chunks_ident_docsize")
    if n == 0:
        problems.append("no chunks")
    if nv != n:
        problems.append(f"vec rows {nv} != chunks {n}")
    if nf != n:
        problems.append(f"fts rows {nf} != chunks {n}")
    if ni != n:
        problems.append(f"ident rows {ni} != chunks {n}")
    if (o := q("SELECT count(*) FROM chunks c LEFT JOIN docs d USING(doc_id) WHERE d.doc_id IS NULL")):
        problems.append(f"{o} orphan chunks")
    if (o := q("SELECT count(*) FROM docs d WHERE NOT EXISTS (SELECT 1 FROM chunks c WHERE c.doc_id=d.doc_id)")) > 0.02 * max(1, q("SELECT count(*) FROM docs")):
        problems.append(f"{o} docs without chunks")
    return problems


def swap(new_db: Path, link: Path, keep: int = 3) -> None:
    """Atomically repoint `link` (a symlink) at `new_db`; prune old builds beyond `keep`."""
    tmp = link.with_name(link.name + ".tmp")
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    tmp.symlink_to(new_db.name)
    os.replace(tmp, link)
    olds = sorted(link.parent.glob("index-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in olds[keep:]:
        for suffix in ("", "-wal", "-shm"):
            Path(str(p) + suffix).unlink(missing_ok=True)


def stamp() -> str:
    """Build id: second resolution plus milliseconds, so two builds never share an index filename."""
    t = time.time()
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(t)) + f"{int(t * 1000) % 1000:03d}"
