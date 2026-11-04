"""Full index build: parse/chunk (parallel) -> SQLite -> embed (resumable) -> verify -> atomic swap."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import store, vecmat
from .chunker import Chunk
from .config import Config, load_config
from .embed import DOC_PREFIX, MODEL_ID, prod_embedder, prod_server
from .pipeline import PageResult, Processor
from .sync import blob_hashes, head, last_commit_dates, list_pages
from .toc import build_toc
from .urls import Redirects

SEP = " › "
_W: dict = {}


def embed_text(title: str, heading_path: str, context: str, text: str) -> str:
    """Must match Chunk.embed_text."""
    bc = SEP.join(p for p in (title, heading_path) if p)
    return "\n\n".join(p for p in (bc, context, text) if p)


def _init_worker(cfg_path: str) -> None:
    _W["cfg"] = load_config(cfg_path)
    _W["proc"] = {}


def _work(args: tuple[str, list[str]]) -> list[PageResult]:
    name, rels = args
    procs = _W["proc"]
    if name not in procs:
        procs[name] = Processor(_W["cfg"], _W["cfg"].repo(name))
    return [r for rel in rels if (r := procs[name].process(rel))]


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def _insert_page(db: sqlite3.Connection, r: PageResult, blob: str | None, last: str | None) -> int:
    m, d = r.meta, r.doc
    desc = m.get("description") if isinstance(m.get("description"), str) else ""
    s = lambda k: str(m[k]) if m.get(k) is not None else None
    cur = db.execute(
        "INSERT INTO docs(repo,path,url,title,description,ms_service,ms_subservice,ms_topic,ms_date,"
        "last_commit_date,blob_hash,flags) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (d.repo, d.path, d.url, d.title, desc, s("ms.service"), s("ms.subservice"), s("ms.topic"),
         store.normalize_date(m.get("ms.date")), last, blob, ",".join(r.flags)))
    doc_id = cur.lastrowid
    db.executemany("INSERT INTO deps VALUES (?,?)", [(doc_id, p) for p in sorted(r.deps)])
    db.executemany("INSERT INTO links VALUES (?,?)", [(doc_id, u) for u in dict.fromkeys(r.links)])
    for c in r.chunks:
        _insert_chunk(db, doc_id, d.title, desc, c)
    return doc_id


def _insert_chunk(db: sqlite3.Connection, doc_id: int, title: str, desc: str, c: Chunk) -> None:
    hp = SEP.join(c.heading_path)
    v = c.variant
    h = hashlib.sha256((c.embed_text + "\0" + MODEL_ID).encode()).hexdigest()
    cur = db.execute(
        "INSERT INTO chunks(chunk_id,doc_id,heading_path,anchor,variant_tab,variant_pivot,variant_moniker,"
        "parent_id,prev_id,next_id,text,context,token_count,content_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (c.chunk_id, doc_id, hp, c.anchor, ",".join(v.tabs) or None, ",".join(v.pivots) or None,
         ",".join(v.monikers) or None, c.parent_id or None, c.prev_id or None, c.next_id or None,
         c.text, c.context or None, c.token_count, h))
    rid = cur.lastrowid
    db.execute("INSERT INTO chunks_fts(rowid,title,description,heading_path,text) VALUES (?,?,?,?,?)",
               (rid, title, desc, hp, c.text))
    db.execute("INSERT INTO chunks_ident(rowid,tokens) VALUES (?,?)",
               (rid, store.ident_tokens(title, hp, c.text)))


def parse_pages(cfg_path: str, repo_name: str, rels: list[str], workers: int):
    """Yield PageResult for each page of one repo, in order, parsing in parallel."""
    batches = [(repo_name, rels[i : i + 100]) for i in range(0, len(rels), 100)]
    if workers <= 1 or len(batches) <= 1:
        _init_worker(cfg_path)
        for b in batches:
            yield from _work(b)
        return
    with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(cfg_path,)) as pool:
        for res in pool.map(_work, batches):
            yield from res


def phase_parse(cfg: Config, cfg_path: str, db: sqlite3.Connection, repos: list[str] | None,
                limit: int | None, workers: int) -> None:
    t0 = time.time()
    with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(cfg_path,)) as pool:
        for repo in cfg.repos:
            if repos and repo.name not in repos:
                continue
            pages = list_pages(repo)[:limit]
            blobs, dates = blob_hashes(repo), last_commit_dates(repo)
            batches = [(repo.name, pages[i : i + 100]) for i in range(0, len(pages), 100)]
            n = nc = 0
            for res in pool.map(_work, batches):
                for r in res:
                    _insert_page(db, r, blobs.get(r.doc.path), dates.get(r.doc.path))
                    n += 1
                    nc += len(r.chunks)
            red = Redirects.load(repo).map
            db.executemany("INSERT OR REPLACE INTO redirects VALUES (?,?)", red.items())
            store.set_meta(db, **{f"head:{repo.name}": head(repo)})
            db.commit()
            log(f"parsed {repo.name}: {n} pages, {nc} chunks, {len(red)} redirects ({time.time()-t0:.0f}s)")


def calibrate(db: sqlite3.Connection, emb: Embedder, sample: int = 200) -> float:
    rows = db.execute("SELECT token_count, text FROM chunks WHERE rid % (SELECT max(1, count(*)/?) FROM chunks) = 0 "
                      "LIMIT ?", (sample, sample)).fetchall()
    est = sum(r[0] for r in rows) or 1
    real = sum(emb.tokenize_len(r[1]) for r in rows)
    return real / est


def _rows_to_embed(db: sqlite3.Connection):
    return db.execute(
        "SELECT c.rid, c.content_hash, c.token_count, d.title, c.heading_path, c.context, c.text "
        "FROM chunks c JOIN docs d USING(doc_id) "
        "WHERE NOT EXISTS (SELECT 1 FROM chunks_vec v WHERE v.rowid = c.rid) ORDER BY c.rid").fetchall()


def phase_embed(db: sqlite3.Connection, prev: Path | None, group: int = 1500, restart_every: int = 10,
                embedder=None) -> None:
    todo = _rows_to_embed(db)
    log(f"{len(todo)} chunks need vectors")
    if not todo:
        return
    if prev and prev.exists():
        old = store.connect(prev, readonly=True)
        known = dict(old.execute("SELECT content_hash, rid FROM chunks"))
        reuse = [(r[0], known[r[1]]) for r in todo if r[1] in known]
        for i in range(0, len(reuse), 500):
            part = reuse[i : i + 500]
            qs = ",".join("?" * len(part))
            vecs = dict(old.execute(f"SELECT rowid, embedding FROM chunks_vec WHERE rowid IN ({qs})",
                                    [p[1] for p in part]))
            db.executemany("INSERT INTO chunks_vec(rowid, embedding) VALUES (?,?)",
                           [(rid, vecs[o]) for rid, o in part if o in vecs])
        db.commit()
        old.close()
        todo = _rows_to_embed(db)
        log(f"reused {len(reuse)} vectors from previous index; {len(todo)} to embed")
    if embedder is not None:                      # injected backend (tests, alternative servers): no restarts
        _embed_loop(db, todo, embedder, None, group, restart_every, 1.0)
        return
    with prod_server() as srv:
        emb = prod_embedder(srv.url)
        ratio = calibrate(db, emb)
        _embed_loop(db, todo, emb, srv, group, restart_every, ratio)


def _embed_loop(db, todo, emb, srv, group, restart_every, ratio) -> None:
    store.set_meta(db, token_ratio_real_over_est=f"{ratio:.3f}")
    log(f"token estimate calibration: real/est = {ratio:.3f}")
    t0, done = time.time(), 0
    total_tok = sum(r[2] for r in todo)
    tok_done, t_prev, tok_prev = 0, t0, 0
    truncated = 0
    for i in range(0, len(todo), group):
        if srv and i and (i // group) % restart_every == 0:       # every ~15k chunks
            truncated += emb.truncated
            srv.restart()
            emb = prod_embedder(srv.url)
            log("restarted embedding server")
        part = todo[i : i + group]
        texts = [embed_text(r[3], r[4], r[5] or "", r[6]) for r in part]
        vecs = emb.embed(texts, DOC_PREFIX, [int(r[2] * ratio) + 20 for r in part])
        db.executemany("INSERT INTO chunks_vec(rowid, embedding) VALUES (?,?)",
                       [(r[0], v) for r, v in zip(part, vecs)])
        db.commit()
        done += len(part)
        tok_done += sum(r[2] for r in part)
        now = time.time()
        recent = (tok_done - tok_prev) / max(now - t_prev, 1e-6)       # est tokens/s over this group
        t_prev, tok_prev = now, tok_done
        eta = (total_tok - tok_done) / max(recent, 1) / 60
        log(f"embedded {done}/{len(todo)}  recent {recent:.0f} est-tok/s  "
            f"avg {done/(now-t0):.0f} chunks/s  eta {eta:.0f} min (token-based, recent rate)")
    store.set_meta(db, truncated_inputs=truncated + emb.truncated)


def unresolved_fraction(db: sqlite3.Connection) -> float:
    n = db.execute("SELECT count(*) FROM docs").fetchone()[0] or 1
    bad = db.execute("SELECT count(*) FROM docs WHERE flags LIKE '%unresolved%'").fetchone()[0]
    return bad / n


def publish_index(final: Path, link: Path) -> None:
    """Make `final` the live index: exact in-memory vector cache first (a failure only costs speed: searches fall back to
    sqlite-vec, ~13x slower), then the atomic swap. The single publish path of build, update and migrate."""
    try:
        log(f"vecmat cache: {vecmat.build(final)} vectors")
    except Exception as e:
        vecmat.remove(final)
        log(f"vecmat cache failed ({type(e).__name__}: {e}); falling back to sqlite-vec")
    store.swap(final, link)


def build(cfg_path: str, out_dir: Path, *, repos: list[str] | None = None, limit: int | None = None,
          embed: bool = True, resume: Path | None = None, prev: Path | None = None,
          force: bool = False, max_unresolved: float = 0.15, workers: int | None = None, embedder=None) -> Path:
    cfg = load_config(cfg_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    link = out_dir / "current.db"
    if prev is None and link.exists():
        prev = link.resolve()
    if resume:
        part, db = resume, store.connect(resume)
        db.execute("PRAGMA synchronous=OFF")
    else:
        part = out_dir / f"index-{store.stamp()}.partial"
        db = store.create(part)
        store.set_meta(db, schema_version=store.SCHEMA_VERSION, model=MODEL_ID, dims=store.DIMS,
                       built_at=time.strftime("%Y-%m-%dT%H:%M:%S"), limit=limit)
        phase_parse(cfg, cfg_path, db, repos, limit, workers or min(16, os.cpu_count() or 4))
    if not resume:
        build_toc(db, cfg)
    if embed:
        phase_embed(db, prev, embedder=embedder)
    problems = store.health(db) if embed else []
    frac = unresolved_fraction(db)
    if frac > max_unresolved:
        problems.append(f"unresolved include/snippet rate {frac:.1%} > {max_unresolved:.0%}")
    log(f"unresolved include/snippet pages: {frac:.1%}")
    if problems and not force:
        db.close()
        raise SystemExit(f"build NOT published ({part}): " + "; ".join(problems))
    db.execute("ANALYZE")
    db.commit()
    db.execute("PRAGMA journal_mode=DELETE")
    db.close()
    final = part.with_suffix(".db")
    part.rename(final)
    if embed:
        publish_index(final, link)
        log(f"published {final.name} -> {link}")
    return final
