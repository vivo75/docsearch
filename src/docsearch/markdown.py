"""Fence-aware text helpers shared by the parser stages."""
from __future__ import annotations

import re

FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
HEADING = re.compile(r"^(#{1,6})\s+\S")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def fence_mask(lines: list[str]) -> list[bool]:
    """True for lines inside (or delimiting) a fenced code block."""
    mask, opener = [], None
    for ln in lines:
        m = FENCE.match(ln)
        if opener is None:
            opener = m.group(1) if m else None
            mask.append(bool(m))
        else:
            mask.append(True)
            if m and m.group(1)[0] == opener[0] and len(m.group(1)) >= len(opener) and ln.strip().strip(opener[0]) == "":
                opener = None
    return mask


def strip_html_comments(text: str) -> str:
    """Remove <!-- ... --> outside fenced code."""
    lines = text.split("\n")
    mask = fence_mask(lines)
    out, buf = [], []
    for ln, in_f in zip(lines, mask):
        if in_f:
            if buf:
                out.append(_COMMENT.sub("", "\n".join(buf)))
                buf = []
            out.append(ln)
        else:
            buf.append(ln)
    if buf:
        out.append(_COMMENT.sub("", "\n".join(buf)))
    return "\n".join(out)
