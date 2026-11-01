"""Change planning and reverse-dependency invalidation (design 3)."""
from __future__ import annotations

import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .config import EXCLUDE_DIRS, Repo

_NAMES = ("TOC.yml", "toc.yml")


def is_page(rel: str, fmt: str = "md") -> bool:
    parts = rel.split("/")
    if fmt == "azcli-yaml":
        return rel.endswith(".yml") and parts[-1].lower() != "toc.yml"
    return rel.endswith(".md") and not (set(parts[:-1]) & EXCLUDE_DIRS)


def is_indexable(rel: str) -> bool:
    return rel.endswith((".md", ".yml")) or rel.rsplit("/", 1)[-1] in _NAMES or rel.startswith(".openpublishing") or rel == "docfx.json"


def git(repo: Repo, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo.path), *args], check=True, capture_output=True, text=True).stdout


def head(repo: Repo) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def list_pages(repo: Repo) -> list[str]:
    out = git(repo, "ls-files", "-z", "--", "*.yml" if repo.fmt == "azcli-yaml" else "*.md")
    return sorted(p for p in out.split("\0") if p and is_page(p, repo.fmt) and repo.in_scope(p))


@dataclass
class ChangeSet:
    added: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)
    deleted: set[str] = field(default_factory=set)
    renamed: dict[str, str] = field(default_factory=dict)  # old -> new

    @property
    def touched(self) -> set[str]:
        return self.added | self.modified | self.deleted | set(self.renamed) | set(self.renamed.values())


def diff(repo: Repo, old: str, new: str) -> ChangeSet:
    """`git diff --name-status -M old new`, filtered to indexable paths."""
    tok = git(repo, "diff", "--name-status", "-M", "-z", old, new).split("\0")
    cs, i = ChangeSet(), 0
    while i < len(tok) and tok[i]:
        st = tok[i][0]
        if st == "R":
            a, b = tok[i + 1], tok[i + 2]
            i += 3
            if is_indexable(a) or is_indexable(b):
                cs.renamed[a] = b
            continue
        p = tok[i + 1]
        i += 2
        if not is_indexable(p):
            continue
        {"A": cs.added, "D": cs.deleted}.get(st, cs.modified).add(p)
    return cs


class DepGraph:
    """dep file -> pages that include/snippet-reference it (transitively)."""

    def __init__(self) -> None:
        self._rev: dict[str, set[str]] = defaultdict(set)

    def set_deps(self, page: str, deps: set[str]) -> None:
        self.drop(page)
        for d in deps:
            self._rev[d].add(page)

    def drop(self, page: str) -> None:
        for pages in self._rev.values():
            pages.discard(page)

    def dependents(self, dep: str) -> set[str]:
        return set(self._rev.get(dep, ()))

    def affected_pages(self, cs: ChangeSet, prefix: str = "") -> set[str]:
        """Pages to re-process: changed pages plus dependents of any changed file.

        `prefix` (e.g. "azure-docs/") maps repo-relative diff paths onto the corpus-relative
        keys used by IncludeResolver.deps; returned pages are repo-relative.
        """
        todo = {p for p in cs.touched if is_page(p)} - cs.deleted
        for p in cs.touched:
            todo |= {d.removeprefix(prefix) for d in self.dependents(prefix + p) if d.startswith(prefix)}
        return todo - cs.deleted - set(cs.renamed)


def blob_hashes(repo: Repo) -> dict[str, str]:
    """path -> git blob hash at HEAD (one call)."""
    out = {}
    for ent in git(repo, "ls-files", "-s", "-z").split("\0"):
        if ent:
            meta, _, path = ent.partition("\t")
            out[path] = meta.split()[1]
    return out


def last_commit_dates(repo: Repo) -> dict[str, str]:
    """path -> date (YYYY-MM-DD) of the newest commit touching it, from available history."""
    out: dict[str, str] = {}
    date = ""
    for ln in git(repo, "log", "--format=C%cs", "--name-only", "--diff-filter=AMR").split("\n"):
        if ln.startswith("C") and len(ln) == 11 and ln[1:5].isdigit():
            date = ln[1:]
        elif ln:
            out.setdefault(ln, date)
    return out
