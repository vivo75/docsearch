from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

_H1 = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.M)


@dataclass
class Page:
    meta: dict
    body: str
    flags: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        t = self.meta.get("title")
        if isinstance(t, str) and t.strip():
            return t.strip()
        m = _H1.search(self.body)
        return m.group(1) if m else ""


def split_frontmatter(text: str) -> tuple[dict, str, list[str]]:
    """Split a leading `---` YAML block. Delimiter must be on line 1; CRLF tolerated."""
    text = text.lstrip("﻿").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text, ["no_frontmatter"]
    end = re.search(r"^(?:---|\.\.\.)[ \t]*$", text[4:], re.M)
    if not end:
        return {}, text, ["no_frontmatter"]
    raw = text[4 : 4 + end.start()]
    body = text[4 + end.end() :].lstrip("\n")
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}, body, ["bad_frontmatter"]
    if not isinstance(meta, dict):
        return {}, body, ["bad_frontmatter"]
    return meta, body, []


def parse_page(text: str) -> Page:
    meta, body, flags = split_frontmatter(text)
    for k in ("ms.service", "ms.topic"):
        if k not in meta:
            flags = [*flags, f"missing_{k}"] if "no_frontmatter" not in flags else flags
    return Page(meta, body, flags)
