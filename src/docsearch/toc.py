"""Table-of-contents tree for `browse` (design 7.1): toc.yml / TOC.yml -> toc table."""
from __future__ import annotations

import posixpath
import sqlite3
from urllib.parse import urlsplit

import yaml

from . import store
from .config import Config
from .sync import git


def _resolve(repo_rel_dir: str, href: str | None, known: dict[str, tuple[int, str | None]]):
    """Map a TOC href to (doc_id, url) when it points at an indexed page."""
    if not href or href.startswith(("http://", "https://")):
        return None, None
    path = urlsplit(href).path
    if path.startswith("~/"):
        full = path[2:]
    elif path.startswith("/"):
        return None, None                      # site-absolute: another docset
    else:
        full = posixpath.normpath(posixpath.join(repo_rel_dir, path))
    for cand in (full, full + ".md", posixpath.join(full, "index.md"), full.removesuffix(".yml") + ".md"):
        if cand in known:
            return known[cand]
    return None, None


def build_toc(db: sqlite3.Connection, cfg: Config) -> int:
    db.executescript("DROP TABLE IF EXISTS toc;" + store.TOC_SCHEMA)
    n = 0
    for repo in cfg.repos:
        names = [r.name for r in cfg.sharing(repo)]          # a TOC may link to pages indexed under a sibling entry
        known = {p: (d, u) for d, p, u in db.execute(
            f"SELECT doc_id, path, url FROM docs WHERE repo IN ({','.join('?' * len(names))})", names)}
        if not known:
            continue
        files = [f for f in git(repo, "ls-files", "-z", "--", "*toc.yml", "*TOC.yml").split("\0")
                 if f and repo.in_scope(f)]                   # each entry owns only the TOC files inside its scope
        for f in files:
            try:
                data = yaml.safe_load((repo.path / f).read_text(encoding="utf-8-sig", errors="replace"))
            except (OSError, yaml.YAMLError):
                continue
            items = data.get("items") if isinstance(data, dict) else data
            n += _insert(db, repo.name, f, posixpath.dirname(f), items, None, known)
    db.commit()
    return n


def _insert(db, repo: str, toc_path: str, base: str, items, parent: int | None, known) -> int:
    if not isinstance(items, list):
        return 0
    n = 0
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            continue
        href = it.get("href") or it.get("topicHref") or it.get("homepage")
        href = href if isinstance(href, str) else None
        doc_id, url = _resolve(base, href, known)
        cur = db.execute(
            "INSERT INTO toc(parent_id, ord, repo, toc_path, name, href, doc_id, url) VALUES (?,?,?,?,?,?,?,?)",
            (parent, i, repo, toc_path, str(it.get("name", "")), href, doc_id, url))
        n += 1 + _insert(db, repo, toc_path, base, it.get("items"), cur.lastrowid, known)
    return n
