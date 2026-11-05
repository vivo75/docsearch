"""Make resolved Markdown readable as plain retrieval text (design 4.4)."""
from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import unquote

from .markdown import fence_mask
from .urls import SITE

_IMG_DIRECTIVE = re.compile(r"^(\s*):{3,}\s*image\b(.*?)(?::{3,})?\s*$")
_IMG_END = re.compile(r"^\s*:{3,}\s*image-end\s*:{3,}\s*$|^\s*:{3,}\s*image-end\s*$")
_ATTR = re.compile(r"([\w-]+)\s*=\s*\"([^\"]*)\"")
_MD_IMG = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_ALERT = re.compile(r"^(\s*>\s*)\[!(NOTE|TIP|WARNING|IMPORTANT|CAUTION|INFORMATION|ALERT)\]\s*$", re.I)
_DIV = re.compile(r"^\s*(?:>\s*)?\[!div[^\]]*\]\s*$", re.I)
_LINK = re.compile(r"(?<!\!)\[([^\]]*)\]\(\s*([^)\s]+)((?:\s+\"[^\"]*\")?)\s*\)")
LinkMapper = Callable[[str], "str | None"]   # relative/rooted doc target (no anchor) -> public URL


def normalize(text: str, link_url: LinkMapper | None = None, site: str = SITE) -> tuple[str, list[str]]:
    """Return (text, outgoing link URLs). Fenced code is left untouched. `site` is the origin that site-rooted links (`/docs/x`) resolve against
    (the repo's own site, e.g. https://kubernetes.io, not always Learn)."""
    lines = text.split("\n")
    mask = fence_mask(lines)
    out: list[str] = []
    links: list[str] = []
    for ln, in_f in zip(lines, mask):
        if in_f:
            out.append(ln)
            continue
        if _IMG_END.match(ln) or _DIV.match(ln):
            continue
        if (m := _IMG_DIRECTIVE.match(ln)):
            alt = dict(_ATTR.findall(m.group(2))).get("alt-text", "").strip()
            if alt:
                out.append(f"{m.group(1)}[Image: {alt}]")
            continue
        if (m := _ALERT.match(ln)):
            out.append(f"{m.group(1)}{m.group(2).capitalize()}:")
            continue
        ln = _MD_IMG.sub(lambda mm: f"[Image: {mm.group(1).strip()}]" if mm.group(1).strip() else "", ln)
        if "](" in ln:
            ln = _LINK.sub(lambda mm: _rewrite(mm, link_url, links, site), ln)
        out.append(ln)
    return "\n".join(out), links


def _rewrite(m: re.Match, link_url: LinkMapper | None, links: list[str], site: str = SITE) -> str:
    label, target, title = m.group(1), m.group(2), m.group(3)
    if target.startswith("#") or target.startswith("mailto:") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
        if target.startswith(("http://", "https://")):
            links.append(target)
        return m.group(0)
    if target.startswith("//"):
        return m.group(0)
    path, hash_, frag = target.partition("#")
    path = unquote(path.split("?")[0])
    url = None
    if path.startswith("/"):
        url = site + path.lower().rstrip("/") if not path.endswith((".md", ".yml")) else None
    elif link_url and path.endswith(".md"):
        url = link_url(path)
    if not url:
        return m.group(0)
    full = url + (hash_ + frag if frag else "")
    links.append(full)
    return f"[{label}]({full}{title})"
