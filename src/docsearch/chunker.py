"""Heading-aware, variant-aware chunking (design 5).

Pipeline: resolved page text -> variant segments -> block units (heading / paragraph / list /
table / code / quote) -> packed chunks. Chunks of different variants are never merged.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .markdown import FENCE, HEADING
from .urls import Anchors
from .variants import Segment, Variant, split_variants

TARGET_MIN = 300     # soft: break at H3+ only once the chunk has this many tokens
TARGET_MAX = 600
HARD_CAP = 800
MERGE_BELOW = 100
OVERLAP = 0.12
CONTEXT_TOKENS = 80

_TOK = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")
_LIST_ITEM = re.compile(r"^(\s{0,3})([-*+]|\d+[.)])\s+")
_TABLE = re.compile(r"^\s*\|")
_QUOTE = re.compile(r"^\s{0,3}>")
_SENT = re.compile(r"(?<=[.!?])\s+")
_PREREQ = re.compile(r"^prerequisites?$", re.I)


def count_tokens(s: str) -> int:
    """Cheap subword-ish estimate; calibrate against the real embedder before tuning."""
    n = 0
    for t in _TOK.findall(s):
        c = t[0]
        n += 1 + (len(t) // 7 if c.isalpha() else len(t) // 3 if c.isdigit() else 0)
    return n


def truncate_tokens(s: str, limit: int) -> str:
    if count_tokens(s) <= limit:
        return s
    out, n = [], 0
    for w in s.split():
        n += count_tokens(w)
        if n > limit:
            break
        out.append(w)
    return " ".join(out) + " …"


@dataclass
class DocInfo:
    repo: str
    path: str
    title: str
    url: str | None = None


@dataclass
class Unit:
    kind: str                      # heading | para | list | table | code | quote
    lines: list[str]
    variant: Variant
    path: tuple[str, ...]          # heading path in force at the start of the unit
    anchor: str
    level: int = 0                 # headings only
    items: list[list[str]] = field(default_factory=list)  # list units: one entry per item

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def tokens(self) -> int:
        return count_tokens(self.text)


@dataclass
class Chunk:
    chunk_id: str
    doc: DocInfo
    heading_path: tuple[str, ...]
    anchor: str
    variant: Variant
    text: str                      # display body
    context: str                   # embed-only: variant preamble / prerequisites
    token_count: int
    parent_id: str = ""            # first chunk of the same H2 section and variant
    prev_id: str = ""
    next_id: str = ""

    @property
    def breadcrumb(self) -> str:
        return " › ".join((self.doc.title, *self.heading_path)) if self.doc.title else " › ".join(self.heading_path)

    @property
    def embed_text(self) -> str:
        parts = [self.breadcrumb]
        if self.context:
            parts.append(self.context)
        parts.append(self.text)
        return "\n\n".join(parts)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.embed_text.encode()).hexdigest()


# ---------------------------------------------------------------- block parsing

def _indent(l: str) -> int:
    return len(l) - len(l.lstrip(" \t"))


def parse_units(seg: Segment, state: "_State") -> list[Unit]:
    lines = seg.text.split("\n")
    out: list[Unit] = []
    i, n = 0, len(lines)

    def mk(kind, ls, **kw):
        a = state.stack[-1][2] if state.stack else ""
        return Unit(kind, ls, seg.variant, state.path(), a, **kw)

    while i < n:
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if (m := HEADING.match(ln)):
            lvl = len(m.group(1))
            text = re.sub(r"\s+#+\s*$", "", ln[lvl:].strip())
            text = re.sub(r"<[^>]+>", "", text).strip() or text
            state.push(lvl, text)
            out.append(mk("heading", [ln], level=lvl))
            i += 1
        elif FENCE.match(ln) and _indent(ln) <= 3:
            j = _fence_end(lines, i)
            out.append(mk("code", lines[i:j]))
            i = j
        elif _LIST_ITEM.match(ln):
            j, items = _list_end(lines, i)
            out.append(mk("list", lines[i:j], items=items))
            i = j
        elif _TABLE.match(ln):
            j = i
            while j < n and _TABLE.match(lines[j]):
                j += 1
            out.append(mk("table", lines[i:j]))
            i = j
        elif _QUOTE.match(ln):
            j = i
            while j < n and lines[j].strip() and (_QUOTE.match(lines[j]) or j > i):
                if not _QUOTE.match(lines[j]) and (HEADING.match(lines[j]) or _LIST_ITEM.match(lines[j])):
                    break
                j += 1
            out.append(mk("quote", lines[i:j]))
            i = j
        else:
            j = i + 1
            while j < n and lines[j].strip() and not (
                HEADING.match(lines[j]) or (FENCE.match(lines[j]) and _indent(lines[j]) <= 3)
                or _LIST_ITEM.match(lines[j]) or _TABLE.match(lines[j]) or _QUOTE.match(lines[j])
            ):
                j += 1
            out.append(mk("para", lines[i:j]))
            i = j
    return out


def _fence_end(lines: list[str], i: int) -> int:
    ch = FENCE.match(lines[i]).group(1)
    for j in range(i + 1, len(lines)):
        m = FENCE.match(lines[j])
        if m and m.group(1)[0] == ch[0] and len(m.group(1)) >= len(ch) and lines[j].strip().strip(ch[0]) == "":
            return j + 1
    return len(lines)


def _list_end(lines: list[str], i: int) -> tuple[int, list[list[str]]]:
    """A list runs while lines are indented, further items, or blank lines followed by either."""
    n, j = len(lines), i
    items: list[list[str]] = []
    while j < n:
        ln = lines[j]
        if FENCE.match(ln) and _indent(ln) > 0:      # indented fence: swallow it whole
            k = _fence_end(lines, j)
            items[-1].extend(lines[j:k])
            j = k
            continue
        if not ln.strip():
            k = j
            while k < n and not lines[k].strip():
                k += 1
            if k < n and (_indent(lines[k]) > 0 or _LIST_ITEM.match(lines[k])) and not HEADING.match(lines[k]):
                items[-1].extend(lines[j:k])
                j = k
                continue
            break
        if _LIST_ITEM.match(ln) and _indent(ln) <= 3:
            items.append([ln])
        elif items and (_indent(ln) > 0 or not (HEADING.match(ln) or _TABLE.match(ln) or _QUOTE.match(ln))):
            if HEADING.match(ln):
                break
            items[-1].append(ln)
        else:
            break
        j += 1
    return j, items


class _State:
    def __init__(self) -> None:
        self.stack: list[tuple[int, str, str]] = []
        self.anchors = Anchors()

    def push(self, lvl: int, text: str) -> None:
        while self.stack and self.stack[-1][0] >= lvl:
            self.stack.pop()
        self.stack.append((lvl, text, self.anchors.make(text)))

    def path(self) -> tuple[str, ...]:
        return tuple(t for l, t, _ in self.stack if l >= 2)


# ---------------------------------------------------------------- oversize splitting

def _group(parts: list[str], cap: int, sep: str, overlap: bool = False) -> list[str]:
    out, cur, n = [], [], 0
    for p in parts:
        t = count_tokens(p)
        if cur and n + t > cap:
            out.append(sep.join(cur))
            keep: list[str] = []
            if overlap:
                k = 0
                for q in reversed(cur):
                    if k + count_tokens(q) > OVERLAP * cap:
                        break
                    keep.insert(0, q)
                    k += count_tokens(q)
            cur, n = keep, sum(count_tokens(q) for q in keep)
        cur.append(p)
        n += t
    if cur:
        out.append(sep.join(cur))
    return out


def split_unit(u: Unit, cap: int = TARGET_MAX) -> list[Unit]:
    def clone(ls: list[str]) -> Unit:
        return Unit(u.kind, ls, u.variant, u.path, u.anchor)

    if u.tokens <= HARD_CAP:
        return [u]
    if any(count_tokens(l) > cap for l in u.lines):
        lines = [w for l in u.lines for w in (_hard_words(l, cap) if count_tokens(l) > cap else [l])]
        u = Unit(u.kind, lines, u.variant, u.path, u.anchor, u.level, u.items if u.kind != "list" else [])
    if u.kind == "code":
        fence_open, body, fence_close = u.lines[0], u.lines[1:-1], u.lines[-1]
        if not FENCE.match(fence_close) or len(u.lines) < 3:
            body, fence_close = u.lines[1:], fence_open.strip()[:3]
        return [clone([fence_open, *g.split("\n"), fence_close]) for g in _group(body, cap, "\n")]
    if u.kind == "table":
        head, rows = u.lines[:2], u.lines[2:]
        return [clone([*head, *g.split("\n")]) for g in _group(rows, cap, "\n")]
    if u.kind == "list" and len(u.items) > 1:
        pieces = []
        for g in _group(["\n".join(it) for it in u.items], cap, "\n"):
            c = clone(g.split("\n"))
            c.kind = "list"
            pieces.extend(_split_lines(c, cap) if c.tokens > HARD_CAP else [c])
        return pieces
    if u.kind in ("list", "quote"):
        return _split_lines(u, cap)
    sents = [s for l in u.lines for s in (_SENT.split(l) if l.strip() else [l])]
    sents = [w for s in sents for w in (_hard_words(s, cap) if count_tokens(s) > cap else [s])]
    return [clone(g.split("\n") if u.kind != "para" else [g]) for g in _group(sents, cap, " ", overlap=True)]


def _split_lines(u: Unit, cap: int) -> list[Unit]:
    """Line-wise split that never leaves a code fence open across a cut."""
    pieces: list[list[str]] = [[]]
    n, fence = 0, None
    for ln in u.lines:
        t = count_tokens(ln)
        if pieces[-1] and n + t > cap:
            if fence:
                pieces[-1].append(FENCE.match(fence).group(0).rstrip("`~ \t") + FENCE.match(fence).group(1))
            pieces.append([fence] if fence else [])
            n = count_tokens(fence) if fence else 0
        pieces[-1].append(ln)
        n += t
        if (m := FENCE.match(ln)):
            fence = None if fence else ln
    return [Unit(u.kind, p, u.variant, u.path, u.anchor) for p in pieces if p]


def _hard_words(s: str, cap: int) -> list[str]:
    words = [w for word in s.split(" ")
             for w in ([word[i : i + cap] for i in range(0, len(word), cap)] if count_tokens(word) > cap else [word])]
    return _group(words, cap, " ")


# ---------------------------------------------------------------- packing

def _id(doc: DocInfo, path: tuple[str, ...], v: Variant, ordinal: int) -> str:
    key = "\0".join([doc.repo, doc.path, "›".join(path), repr(v), str(ordinal)])
    return "c_" + hashlib.sha1(key.encode()).hexdigest()[:16]


def chunk_page(doc: DocInfo, text: str) -> list[Chunk]:
    state = _State()
    units: list[Unit] = []
    for seg in split_variants(text):
        units.extend(parse_units(seg, state))
    # the page H1 duplicates the title; keep any other H1
    units = [u for u in units if not (u.kind == "heading" and u.level == 1
                                      and u.lines[0].lstrip("# ").strip().lower() == doc.title.lower())]
    return _finish(doc, _pack(units))


@dataclass
class _Draft:
    units: list[Unit]
    context: str = ""

    @property
    def variant(self) -> Variant:
        return self.units[0].variant

    @property
    def tokens(self) -> int:
        return sum(u.tokens for u in self.units)


def _pack(units: list[Unit]) -> list[_Draft]:
    drafts: list[_Draft] = []
    cur: list[Unit] = []
    cur_n, cur_ctx, preamble = 0, "", ""

    def flush(carry_headings: bool = False) -> list[Unit]:
        """Close the current chunk; trailing headings move to the next chunk instead of dangling."""
        nonlocal cur, cur_n, cur_ctx
        carry: list[Unit] = []
        while carry_headings and cur and cur[-1].kind == "heading":
            carry.insert(0, cur.pop())
        if cur:
            drafts.append(_Draft(cur, cur_ctx))
        cur, cur_n, cur_ctx = [], 0, ""
        return carry

    for u in units:
        # remember the shared intro so every variant chunk of the group can carry it as context
        if u.variant.is_shared:
            if u.kind == "heading":
                preamble = ""
            elif u.kind in ("para", "list", "quote"):
                preamble = truncate_tokens(u.text, CONTEXT_TOKENS)
        ctx = "" if u.variant.is_shared else preamble
        if cur and cur[0].variant != u.variant:
            flush()
        if u.kind == "heading" and cur and (u.level <= 2 or cur_n >= TARGET_MIN):
            flush()
        for piece in split_unit(u):
            if cur and piece.kind != "heading" and cur_n + piece.tokens > TARGET_MAX:
                cur = flush(carry_headings=True)
                cur_n, cur_ctx = sum(p.tokens for p in cur), ctx
            if not cur:
                cur_ctx = ctx
            cur.append(piece)
            cur_n += piece.tokens
    flush()
    return _merge_small(drafts)


def _merge_small(drafts: list[_Draft]) -> list[_Draft]:
    out: list[_Draft] = []
    for d in drafts:
        if out and d.tokens < MERGE_BELOW and out[-1].variant == d.variant and out[-1].tokens + d.tokens <= HARD_CAP:
            out[-1].units.extend(d.units)
        else:
            out.append(d)
    # a tiny leading chunk joins the next one of the same variant
    if len(out) > 1 and out[0].tokens < MERGE_BELOW and out[0].variant == out[1].variant \
            and out[0].tokens + out[1].tokens <= HARD_CAP:
        out[1].units[0:0] = out[0].units
        out[1].context = out[1].context or out[0].context
        out.pop(0)
    return out


def _finish(doc: DocInfo, drafts: list[_Draft]) -> list[Chunk]:
    chunks: list[Chunk] = []
    ordinals: dict[tuple, int] = {}
    prereq = ""
    for d in drafts:
        first = d.units[0]
        us = d.units
        title_path = first.path
        if us[0].kind == "heading" and us[0].lines[0].lstrip("# ").strip() == (title_path[-1] if title_path else None):
            us = us[1:]
        body = "\n\n".join(u.text for u in us).strip()
        if not body:
            continue
        key = (first.path, first.variant)
        o = ordinals[key] = ordinals.get(key, -1) + 1
        ctx = d.context
        if prereq and first.variant.is_shared and first.path[:1] and not _PREREQ.match(first.path[0]):
            ctx = (ctx + "\n" if ctx else "") + prereq
            prereq = ""
        if first.path and _PREREQ.match(first.path[0]) and first.variant.is_shared and count_tokens(body) <= 350:
            prereq = "Prerequisites: " + truncate_tokens(" ".join(body.split()), CONTEXT_TOKENS)
        chunks.append(Chunk(
            chunk_id=_id(doc, first.path, first.variant, o), doc=doc, heading_path=first.path,
            anchor=first.anchor, variant=first.variant, text=body, context=ctx,
            token_count=count_tokens(body),
        ))
    _link(chunks)
    return chunks


def _link(chunks: list[Chunk]) -> None:
    """prev/next among chunks of the same variant; parent = first chunk of the H2 section."""
    last: dict[Variant, Chunk] = {}
    section_first: dict[tuple, str] = {}
    for c in chunks:
        p = last.get(c.variant)
        if p:
            p.next_id, c.prev_id = c.chunk_id, p.chunk_id
        last[c.variant] = c
        k = (c.heading_path[:1], c.variant)
        c.parent_id = section_first.setdefault(k, c.chunk_id)
