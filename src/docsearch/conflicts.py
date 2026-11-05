"""Curated notes about pages that contradict each other (conflicts.toml, Backlog 8). Informational: they ride along in `warnings`."""
from __future__ import annotations

import sqlite3
import tomllib
from pathlib import Path


def load(path: Path) -> list[dict]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")).get("conflict", [])
    except (OSError, tomllib.TOMLDecodeError):
        return []


def _norm(s: str) -> str:
    return " ".join(s.replace("_", "").replace("*", "").lower().split())


def active(db: sqlite3.Connection, conflicts: list[dict]) -> list[dict]:
    """The conflicts whose every evidence phrase is still in the indexed page: a page that Microsoft has fixed switches its note off."""
    out = []
    for c in conflicts:
        ok = bool(c.get("evidence")) and bool(c.get("note"))
        for ev in c.get("evidence", []):
            repo, _, path = ev["page"].partition("/")
            want = _norm(ev["text"])
            ok = ok and any(want in _norm(t) for (t,) in db.execute(
                "SELECT c.text FROM chunks c JOIN docs d ON d.doc_id = c.doc_id WHERE d.repo = ? AND d.path = ?", (repo, path)))
        if ok:
            out.append(c)
    return out


def notes(conflicts: list[dict], sources: set[str]) -> list[str]:
    return [f"conflicting sources ({c['id']}): {c['note']}" for c in conflicts if sources & set(c["pages"])]
