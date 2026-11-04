"""Incremental index update (design 3, 9.1): git diff + dependency invalidation -> patched COPY -> verify -> atomic swap."""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import store
from .build import _insert_page, log, parse_pages, phase_embed, publish_index, unresolved_fraction
from .config import Config, Repo, load_config
from .pipeline import Processor
from .sync import blob_hashes, diff, head, is_page, last_commit_dates, list_pages
from .toc import build_toc
from .urls import Redirects


@dataclass
class RepoPlan:
    old: str | None
    new: str
    full: bool = False                                   # old HEAD unusable -> reprocess the whole repo
    changed: set[str] = field(default_factory=set)       # repo-relative paths touched (any file type)
    pages: set[str] = field(default_factory=set)         # pages to (re)process
    removed: set[str] = field(default_factory=set)       # pages to drop


@dataclass
class Plan:
    repos: dict[str, RepoPlan]

    @property
    def n_reprocess(self) -> int:
        return sum(len(p.pages) for p in self.repos.values())

    @property
    def n_removed(self) -> int:
        return sum(len(p.removed) for p in self.repos.values())

    @property
    def empty(self) -> bool:
        return not (self.n_reprocess or self.n_removed or any(p.changed for p in self.repos.values()))


def pull(cfg: Config) -> dict[str, str]:
    """`git pull --ff-only` every repo; a failure on one repo is reported, not fatal."""
    out = {}
    for repo in cfg.checkouts():               # entries sharing a checkout are pulled once
        r = subprocess.run(["git", "-C", str(repo.path), "pull", "--ff-only", "--quiet"], capture_output=True, text=True)
        status = "ok" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["failed"])[-1][:200]
        for e in cfg.sharing(repo):
            out[e.name] = status
    return out


def make_plan(cfg: Config, db: sqlite3.Connection) -> Plan:
    meta = store.get_meta(db)
    repos: dict[str, RepoPlan] = {}
    for repo in cfg.repos:
        rp = RepoPlan(meta.get(f"head:{repo.name}"), head(repo))
        repos[repo.name] = rp
        if rp.old == rp.new:
            continue
        try:
            if not rp.old:
                raise subprocess.CalledProcessError(1, "no recorded head")
            cs = diff(repo, rp.old, rp.new)
        except subprocess.CalledProcessError:
            rp.full = True                                # shallow clone lost the old commit, or first run
            rp.pages = set(list_pages(repo))
            known = {p for (p,) in db.execute("SELECT path FROM docs WHERE repo=?", (repo.name,))}
            rp.removed = known - rp.pages
            rp.changed = {"<full>"}
            continue
        rp.changed = cs.touched
        rp.pages = {p for p in (cs.added | cs.modified | set(cs.renamed.values())) if is_page(p, repo.fmt) and repo.in_scope(p)}
        rp.removed = {p for p in (cs.deleted | set(cs.renamed)) if is_page(p, repo.fmt) and repo.in_scope(p)}
    # pages whose includes/snippets changed (the dependency may live in another repo)
    root = cfg.root.resolve()          # deps are stored relative to the corpus root: <checkout dir>/<file>
    touched = {f"{cfg.repo(n).rel_dir(root)}/{p}" for n, rp in repos.items() if not rp.full for p in rp.changed}
    deleted_or_changed = list(touched)
    for i in range(0, len(deleted_or_changed), 500):
        part = deleted_or_changed[i : i + 500]
        qs = ",".join("?" * len(part))
        for repo_name, path in db.execute(
                f"SELECT DISTINCT d.repo, d.path FROM deps x JOIN docs d ON d.doc_id = x.doc_id WHERE x.dep_path IN ({qs})", part):
            rp = repos[repo_name]
            if not rp.full and path not in rp.removed:
                rp.pages.add(path)
    # a repo that is reprocessed in full may have changed any file: pages of OTHER repos that include or snippet from it are stale too
    for n, rp in repos.items():
        if not rp.full:
            continue
        prefix = cfg.repo(n).rel_dir(root) + "/"
        for repo_name, path in db.execute(
                "SELECT DISTINCT d.repo, d.path FROM deps x JOIN docs d ON d.doc_id = x.doc_id "
                "WHERE substr(x.dep_path, 1, ?) = ?", (len(prefix), prefix)):
            other = repos[repo_name]
            if not other.full and path not in other.removed:
                other.pages.add(path)
    _heal_unresolved(cfg, db, repos)
    for name, rp in repos.items():                        # a page can't be both reprocessed and removed
        rp.pages -= rp.removed
        rp.pages = {p for p in rp.pages if (cfg.repo(name).path / p).exists()}
    return Plan(repos)


def _heal_unresolved(cfg: Config, db: sqlite3.Connection, repos: dict[str, RepoPlan]) -> int:
    """Reprocess pages flagged *_unresolved whose includes/snippets resolve now (a missing include file appeared).

    An unresolved include is never recorded in `deps`, so a file that shows up later (a cloned dependent repo, a
    reconstructed stand-in) triggers no git change. Re-resolving the flagged pages and comparing against the stored
    deps finds exactly those that gained a dependency. Cost: one read + include expansion per flagged page.
    """
    procs: dict[str, Processor] = {}
    n = 0
    for doc_id, repo_name, path in db.execute(
            "SELECT doc_id, repo, path FROM docs WHERE flags LIKE '%unresolved%'").fetchall():
        rp = repos.get(repo_name)
        if rp is None or rp.full or path in rp.pages or path in rp.removed:
            continue
        proc = procs.get(repo_name)
        if proc is None:
            proc = procs[repo_name] = Processor(cfg, cfg.repo(repo_name))
        now = proc.deps(path)
        if now is None:
            continue
        known = {d for (d,) in db.execute("SELECT dep_path FROM deps WHERE doc_id=?", (doc_id,))}
        if now - known:
            rp.pages.add(path)
            n += 1
    return n


def _delete_docs(db: sqlite3.Connection, repo: str, paths: set[str]) -> int:
    n = 0
    for path in paths:
        row = db.execute("SELECT doc_id FROM docs WHERE repo=? AND path=?", (repo, path)).fetchone()
        if not row:
            continue
        doc_id = row[0]
        rids = [r[0] for r in db.execute("SELECT rid FROM chunks WHERE doc_id=?", (doc_id,))]
        for table in ("chunks_vec", "chunks_fts", "chunks_ident"):
            db.executemany(f"DELETE FROM {table} WHERE rowid = ?", [(r,) for r in rids])
        for sql in ("DELETE FROM chunks WHERE doc_id=?", "DELETE FROM deps WHERE doc_id=?",
                    "DELETE FROM links WHERE src_doc_id=?", "DELETE FROM docs WHERE doc_id=?"):
            db.execute(sql, (doc_id,))
        n += 1
    return n


def update(cfg_path: str, out_dir: Path, *, do_pull: bool = False, dry_run: bool = False, force: bool = False,
           max_unresolved: float = 0.15, workers: int | None = None, embedder=None, canary=None) -> dict:
    cfg = load_config(cfg_path)
    link = out_dir / "current.db"
    src = link.resolve()
    stats: dict = {"source": src.name}
    if do_pull:
        stats["pull"] = pull(cfg)
        for name, status in stats["pull"].items():
            if status != "ok":
                log(f"pull {name}: {status}")
    ro = store.connect(src, readonly=True)
    plan = make_plan(cfg, ro)
    ro.close()
    for name, rp in plan.repos.items():
        if rp.old != rp.new:
            log(f"{name}: {(rp.old or 'none')[:8]} -> {rp.new[:8]}  {'FULL reprocess' if rp.full else f'{len(rp.changed)} files'}"
                f"; reprocess {len(rp.pages)} pages, remove {len(rp.removed)}")
    stats.update(reprocess=plan.n_reprocess, removed=plan.n_removed)
    if plan.empty:
        log("index is up to date")
        stats["status"] = "up-to-date"
        return stats
    if dry_run:
        stats["status"] = "dry-run"
        return stats

    dst = out_dir / f"index-{store.stamp()}.partial"
    shutil.copyfile(src, dst)                             # the live index is never modified
    db = store.connect(dst)
    try:
        db.execute("PRAGMA synchronous=OFF")
        removed = 0
        for name, rp in plan.repos.items():
            # reprocessed pages are deleted first and re-inserted; vectors of unchanged chunks come back via content hash
            removed += _delete_docs(db, name, rp.removed | rp.pages)
        db.commit()
        workers = workers or min(16, os.cpu_count() or 4)
        added = chunks = 0
        for name, rp in plan.repos.items():
            if not rp.pages:
                continue
            repo = cfg.repo(name)
            blobs, dates = blob_hashes(repo), last_commit_dates(repo)
            for r in parse_pages(cfg_path, name, sorted(rp.pages), workers):
                _insert_page(db, r, blobs.get(r.doc.path), dates.get(r.doc.path))
                added += 1
                chunks += len(r.chunks)
            db.commit()
        # Redirects: rebuilt from every entry when any repo moved. A per-repo `DELETE ... LIKE url_base%` wiped other
        # entries' rows: url_bases are shared (azure-docs/aks/monitor/compute, the two Azure CLI entries) or prefixes of
        # each other (.../azure vs .../azure/developer), and rows carry no repo. Loading all of them takes seconds.
        if any(rp.old != rp.new for rp in plan.repos.values()):
            db.execute("DELETE FROM redirects")
            for repo in cfg.repos:
                db.executemany("INSERT OR REPLACE INTO redirects VALUES (?,?)", Redirects.load(repo).map.items())
        for name, rp in plan.repos.items():
            store.set_meta(db, **{f"head:{name}": rp.new})
            if rp.old:                                    # lets `docsearch changes` report what this update brought in
                store.set_meta(db, **{f"prev_head:{name}": rp.old})
        stats.update(pages_written=added, chunks_written=chunks, docs_deleted=removed)
        n_toc = build_toc(db, cfg)
        store.set_meta(db, built_at=time.strftime("%Y-%m-%dT%H:%M:%S"), updated_from=src.name, toc_nodes=n_toc)
        db.commit()
        phase_embed(db, src, embedder=embedder)           # only chunks without a vector are embedded
        problems = store.health(db)
        frac = unresolved_fraction(db)
        if frac > max_unresolved:
            problems.append(f"unresolved include/snippet rate {frac:.1%} > {max_unresolved:.0%}")
        if canary and not problems:
            problems += canary(dst)
        stats["problems"] = problems
        if problems and not force:
            raise RuntimeError("; ".join(problems))
        db.execute("ANALYZE")
        db.commit()
        db.execute("PRAGMA journal_mode=DELETE")
        db.close()
    except BaseException:
        db.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(dst) + suffix).unlink(missing_ok=True)
        raise
    final = dst.with_suffix(".db")
    dst.rename(final)
    publish_index(final, link)
    stats.update(status="published", index=final.name)
    log(f"published {final.name}: {added} pages / {chunks} chunks re-written, {removed} docs dropped")
    return stats


def verify(cfg_path: str, db_path: Path, sample: int = 200, seed: int = 1) -> dict:
    """Weekly consistency check: re-process a random sample of pages and compare with the index."""
    import random

    from .pipeline import Processor
    cfg = load_config(cfg_path)
    db = store.connect(db_path, readonly=True)
    rows = db.execute("SELECT doc_id, repo, path FROM docs").fetchall()
    random.Random(seed).shuffle(rows)
    procs, bad, checked = {}, [], 0
    for doc_id, repo, path in rows[:sample]:
        proc = procs.setdefault(repo, Processor(cfg, cfg.repo(repo)))
        res = proc.process(path)
        if not res:
            bad.append((repo, path, "file missing"))
            continue
        want = {c.chunk_id for c in res.chunks}
        have = {r[0] for r in db.execute("SELECT chunk_id FROM chunks WHERE doc_id=?", (doc_id,))}
        checked += 1
        if want != have:
            bad.append((repo, path, f"index has {len(have)} chunks, fresh parse {len(want)}"))
    return {"checked": checked, "mismatches": len(bad), "examples": bad[:10]}
