"""Resolve DocFX `[!INCLUDE]` and code-snippet references in one pass (design 4.2, 4.3)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from .frontmatter import split_frontmatter
from .markdown import HEADING, fence_mask, strip_html_comments
from .snippets import parse_directive, render

MAX_DEPTH = 5
INCLUDE = re.compile(r"\[!INCLUDE\s*\[[^\]]*\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)\s*\]", re.I)


@dataclass
class Resolved:
    text: str
    deps: set[str] = field(default_factory=set)         # paths relative to the corpus root, transitive
    unresolved: list[str] = field(default_factory=list)  # includes
    snippets_unresolved: list[str] = field(default_factory=list)


class IncludeResolver:
    """Expands includes and snippets for files in one repo.

    `~/x` is tried under the repo root first, then under the corpus root, so that
    dependent repositories checked out as siblings (e.g. `~/reusable-content/...`) resolve.
    Nothing outside `corpus_root` is ever read.
    """

    def __init__(self, repo_root: Path, corpus_root: Path | None = None):
        self.root = repo_root.resolve()
        self.corpus = (corpus_root or repo_root).resolve()
        self._cache: dict[Path, str | None] = {}

    def _read(self, p: Path) -> str | None:
        if p not in self._cache:
            try:
                _, body, _ = split_frontmatter(p.read_text(encoding="utf-8", errors="replace"))
                self._cache[p] = strip_html_comments(body)
            except OSError:
                self._cache[p] = None
        return self._cache[p]

    def _locate(self, ref: str, current: Path) -> Path | None:
        ref = unquote(ref.split("#")[0].split("?")[0]).replace("\\", "/")
        if ref.startswith("~/"):
            rel = ref[2:].lstrip("/")
            cands = [self.root / rel, self.corpus / rel]
        else:
            cands = [current.parent / ref]
        for c in cands:
            p = c.resolve()
            try:
                p.relative_to(self.corpus)  # confinement
            except ValueError:
                continue
            if p.is_file():
                return p
        return None

    def resolve(self, text: str, path: Path) -> Resolved:
        res = Resolved("")
        text = strip_html_comments(text)   # commented-out includes/tabs must not resolve
        res.text = self._expand(text, path.resolve(), (path.resolve(),), res)
        return res

    def _expand(self, text: str, current: Path, stack: tuple[Path, ...], res: Resolved) -> str:
        lines = text.split("\n")
        mask = fence_mask(lines)
        ctx, out = 0, []
        for ln, in_f in zip(lines, mask):
            if in_f:
                out.append(ln)
                continue
            m = HEADING.match(ln)
            if m:
                ctx = len(m.group(1))
            if ":::" in ln or "[!code" in ln:
                ref = parse_directive(ln)
                if ref:
                    out.append(self._snippet(ref, current, res))
                    continue
            if "[!" in ln:
                ln = INCLUDE.sub(lambda mm: self._one(mm, current, stack, res, ctx), ln)
            out.append(ln)
        return "\n".join(out)

    def _snippet(self, ref, current: Path, res: Resolved) -> str:
        target = self._locate(ref.source, current)
        code = render(ref, target) if target else None
        if target:
            res.deps.add(target.relative_to(self.corpus).as_posix())
        if code is None:
            res.snippets_unresolved.append(ref.source)
            return f"{ref.indent}<!-- unresolved snippet: {ref.source} -->"
        return code

    def _one(self, m: re.Match, current: Path, stack: tuple[Path, ...], res: Resolved, ctx: int) -> str:
        ref = m.group(1)
        target = self._locate(ref, current)
        if target is None:
            res.unresolved.append(ref)
            return f"<!-- unresolved include: {ref} -->"
        res.deps.add(target.relative_to(self.corpus).as_posix())
        if target in stack or len(stack) > MAX_DEPTH:
            res.unresolved.append(ref)
            return f"<!-- unresolved include (cycle/depth): {ref} -->"
        body = self._read(target)
        if body is None:
            res.unresolved.append(ref)
            return f"<!-- unresolved include: {ref} -->"
        body = self._expand(body, target, (*stack, target), res)
        return _shift_headings(body, ctx).strip("\n")


def _shift_headings(body: str, ctx: int) -> str:
    """Push an include's headings below the heading it is inserted under."""
    lines = body.split("\n")
    mask = fence_mask(lines)
    levels = [len(HEADING.match(l).group(1)) for l, f in zip(lines, mask) if not f and HEADING.match(l)]
    if not levels or ctx == 0:
        return body
    shift = max(0, ctx + 1 - min(levels))
    if not shift:
        return body
    out = []
    for l, f in zip(lines, mask):
        mm = None if f else HEADING.match(l)
        out.append("#" * min(6, len(mm.group(1)) + shift) + l[len(mm.group(1)):] if mm else l)
    return "\n".join(out)
