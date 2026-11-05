"""Page -> chunks: wires frontmatter, includes/snippets, normalization, URL mapping and chunking."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .azcli import to_markdown as azcli_to_markdown
from .chunker import Chunk, DocInfo, chunk_page
from .config import Config, Repo
from .frontmatter import parse_page
from .includes import IncludeResolver
from .normalize import normalize
from .urls import SITE, doc_url


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

    def _resolve(self, rel: str):
        path = self.repo.path / rel
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        if self.repo.fmt == "azcli-yaml":
            raw = azcli_to_markdown(raw)
            if raw is None:                 # malformed reference YAML: skip this page, never abort the build
                return None
        page = parse_page(raw)
        return path, page, self.resolver.resolve(page.body, path)

    def deps(self, rel: str) -> set[str] | None:
        """Dependencies the page resolves to now (no normalising or chunking); None if it cannot be read."""
        r = self._resolve(rel)
        return None if r is None else r[2].deps

    def process(self, rel: str) -> PageResult | None:
        r = self._resolve(rel)
        if r is None:
            return None
        path, page, res = r
        text, links = normalize(res.text, lambda target: self._target_url(path, target), self._site())
        info = DocInfo(self.repo.name, rel, page.title, doc_url(self.repo, rel))
        flags = list(page.flags)
        if res.unresolved:
            flags.append("include_unresolved")
        if res.snippets_unresolved:
            flags.append("snippet_unresolved")
        return PageResult(info, page.meta, flags, chunk_page(info, text), res.deps, links,
                          len(res.unresolved), len(res.snippets_unresolved))

    def _site(self) -> str:
        """Origin of the repo's public site: site-rooted links in its pages point there (kubernetes.io), not to Learn."""
        u = urlsplit(self.repo.url_base or "")
        return f"{u.scheme}://{u.netloc}" if u.scheme and u.netloc else SITE

    def _target_url(self, page_path: Path, target: str) -> str | None:
        base = self.repo.docs_dir if target.startswith("~/") else page_path.parent
        rel = target[2:] if target.startswith("~/") else target
        try:
            tp = (base / rel).resolve().relative_to(self.repo.path.resolve())
        except ValueError:
            return None
        return doc_url(self.repo, tp.as_posix())
