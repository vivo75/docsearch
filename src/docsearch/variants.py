"""Split a resolved page into variant-tagged segments: tabs, zone pivots, monikers (design 4.5).

Directive lines are consumed. Each Segment carries the variants active for its text; the
chunker must never merge segments whose variants differ.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .markdown import fence_mask

_TAB = re.compile(r"^[ \t]*(#{1,6})\s+\[(.+?)\]\(#tab/([^)\s]+)\)\s*#*\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+\S")
_HR = re.compile(r"^\s{0,3}(?:-{3,}|(?:\*[ \t]*){3,})\s*$")
_ZONE = re.compile(r"^\s*:{3,}\s*zone\s+(.*?)\s*$")
_ZONE_END = re.compile(r"^\s*:{3,}\s*zone-end\s*$")
_MONIKER = re.compile(r"^\s*:{3,}\s*moniker\s+(.*?)\s*$")
_MONIKER_END = re.compile(r"^\s*:{3,}\s*moniker-end\s*$")
_ATTR = re.compile(r"([\w-]+)\s*=\s*\"([^\"]*)\"")


@dataclass(frozen=True)
class Variant:
    tabs: tuple[str, ...] = ()       # outermost -> innermost tab ids, e.g. ("azure-cli",)
    pivots: tuple[str, ...] = ()     # zone pivot ids; nested zones intersect
    monikers: tuple[str, ...] = ()   # moniker range expressions; nested ranges intersect

    @property
    def is_shared(self) -> bool:
        return not (self.tabs or self.pivots or self.monikers)


@dataclass
class Segment:
    text: str
    variant: Variant


def _attr(s: str, key: str) -> str | None:
    return dict(_ATTR.findall(s)).get(key)


def split_variants(text: str) -> list[Segment]:
    lines = text.split("\n")
    mask = fence_mask(lines)
    tabs: list[tuple[int, str, str]] = []          # (heading level, tab id, label)
    scopes: list[tuple[str, str, int]] = []        # (kind, value, len(tabs) at entry)
    segs: list[Segment] = []
    cur: list[str] = []
    cur_v = Variant()

    def variant() -> Variant:
        return Variant(
            tuple(t[1] for t in tabs),
            tuple(v for k, v, _ in scopes if k == "pivot"),
            tuple(v for k, v, _ in scopes if k == "moniker"),
        )

    def emit(line: str) -> None:
        nonlocal cur, cur_v
        v = variant()
        if v != cur_v:
            if cur:
                segs.append(Segment("\n".join(cur), cur_v))
            cur, cur_v = [], v
        cur.append(line)

    for ln, in_f in zip(lines, mask):
        if in_f:
            emit(ln)
            continue
        if (m := _ZONE.match(ln)):
            piv = _attr(m.group(1), "pivot")
            if piv is not None:
                scopes.append(("pivot", piv, len(tabs)))
            continue
        if _ZONE_END.match(ln):
            _close(scopes, tabs, "pivot")
            continue
        if (m := _MONIKER.match(ln)):
            rng = _attr(m.group(1), "range")
            if rng is not None:
                scopes.append(("moniker", rng, len(tabs)))
            continue
        if _MONIKER_END.match(ln):
            _close(scopes, tabs, "moniker")
            continue
        if (m := _TAB.match(ln)):
            lvl = len(m.group(1))
            while tabs and tabs[-1][0] >= lvl:
                tabs.pop()
            tabs.append((lvl, m.group(3), m.group(2)))
            emit(f"{m.group(1)} {m.group(2)}")
            continue
        if (m := _HEADING.match(ln)):
            lvl = len(m.group(1))
            while tabs and tabs[-1][0] >= lvl:
                tabs.pop()
        elif tabs and _HR.match(ln):
            tabs.pop()      # closes the innermost tab group member; the rule itself is dropped
            continue
        emit(ln)
    if cur:
        segs.append(Segment("\n".join(cur), cur_v))
    return segs


def _close(scopes: list, tabs: list, kind: str) -> None:
    for i in range(len(scopes) - 1, -1, -1):
        if scopes[i][0] == kind:
            n = scopes[i][2]
            del scopes[i]
            del tabs[n:]       # tabs opened inside the zone end with it
            return


# ---------------------------------------------------------------- matching and query inference
# Variant ids are messy in the wild: Learn numbers repeated tab labels ("cli-2",
# "powershell-3"), some tabs carry slashes ("azure-portal/defaultdomain"), case
# varies ("CLI-2"). Token-subset matching handles all of these uniformly, and
# keeps "java" distinct from "javascript".

_TYPO_IDS = {
    "powershellremove": "powershell",   # typos in Learn source (azure-compute-docs
    "cliremove": "cli",                 # articles/virtual-machines/windows/run-command.md)
}
_SPLIT = re.compile(r"[^a-z0-9]+")


def variant_tokens(v: str) -> frozenset[str]:
    return frozenset(t for t in _SPLIT.split(_TYPO_IDS.get(v.lower(), v.lower())) if t)


def variant_matches(element: str, wanted: str) -> bool:
    """Does one variant id (tab or pivot) cover `wanted`? Either token set must
    contain the other, so "azure-cli" covers "cli" and vice versa, "CLI-2" covers
    "cli", and "azure-portal/defaultdomain" covers "azure-portal" — while
    "javascript" does not cover "java"."""
    e, w = variant_tokens(element), variant_tokens(wanted)
    return bool(e & w) and (e <= w or w <= e)


_INFER = [
    (re.compile(r"azure\s+cli|\baz\s+cli\b|\bcli\b|command[\s-]?line"), "cli"),
    (re.compile(r"powershell"), "powershell"),
    (re.compile(r"\bportal\b"), "portal"),
    (re.compile(r"\bpython\b"), "python"),
    (re.compile(r"javascript|\bjs\b|\bnode\.?js\b"), "javascript"),    # not bare "node": AKS "node pool", "node count"
    (re.compile(r"\btypescript\b"), "typescript"),
    (re.compile(r"c#|csharp"), "csharp"),
    (re.compile(r"\bjava(?!script)\b"), "java"),
    (re.compile(r"\bbicep\b"), "bicep"),
    (re.compile(r"\barm\b"), "arm"),
    (re.compile(r"\bterraform\b"), "terraform"),
    (re.compile(r"\bios\b"), "ios"),
    (re.compile(r"\bandroid\b"), "android"),
]
# Contrastive mentions ("without using the portal", "instead of the portal")
# must not trigger a boost for the excluded tool.
_NEG = re.compile(r"\b(without|instead of|rather than|except|avoid)\b[\w\s,\-]*$")


def infer_variants(*texts: str) -> set[str]:
    """Tool/platform keywords mentioned in the query (and expansion)."""
    text = " ".join(texts).lower()
    out = set()
    for rx, kw in _INFER:
        for m in rx.finditer(text):
            if not _NEG.search(text[max(0, m.start() - 30):m.start()]):
                out.add(kw)
                break
    return out
