"""Page -> chunks: wires frontmatter, includes/snippets, normalization, URL mapping and chunking."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .chunker import Chunk, DocInfo, chunk_page
from .config import Config, Repo
from .frontmatter import parse_page
from .includes import IncludeResolver
from .normalize import normalize
from .urls import doc_url


@dataclass
class PageResult:
    doc: DocInfo
    meta: dict
    flags: list[str]
    chunks: list[Chunk]
    deps: set[str]                      # corpus-relative include/snippet files
    links: list[str] = field(default_factory=list)
    unresolved_includes: int = 0
    unresolved_snippets: int = 0


class Processor:
    def __init__(self, cfg: Config, repo: Repo):
        self.cfg, self.repo = cfg, repo
        self.resolver = IncludeResolver(repo.path, cfg.root)

    def process(self, rel: str) -> PageResult | None:
        path = self.repo.path / rel
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        page = parse_page(raw)
        res = self.resolver.resolve(page.body, path)
        text, links = normalize(res.text, lambda target: self._target_url(path, target))
        info = DocInfo(self.repo.name, rel, page.title, doc_url(self.repo, rel))
        flags = list(page.flags)
        if res.unresolved:
            flags.append("include_unresolved")
        if res.snippets_unresolved:
            flags.append("snippet_unresolved")
        return PageResult(info, page.meta, flags, chunk_page(info, text), res.deps, links,
                          len(res.unresolved), len(res.snippets_unresolved))

    def _target_url(self, page_path: Path, target: str) -> str | None:
        base = self.repo.docs_dir if target.startswith("~/") else page_path.parent
        rel = target[2:] if target.startswith("~/") else target
        try:
            tp = (base / rel).resolve().relative_to(self.repo.path.resolve())
        except ValueError:
            return None
        return doc_url(self.repo, tp.as_posix())
