"""Metadata that Learn applies from the repo's docfx.json `build.fileMetadata` when a page's front matter lacks it (e.g. `ms.service`)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

KEYS = ("ms.service", "ms.subservice")


def _glob(pat: str) -> re.Pattern:
    """docfx glob -> regex: `**` crosses directories, `*` and `?` do not."""
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out += "(?:.*/)?"; i += 3
        elif pat.startswith("**", i):
            out += ".*"; i += 2
        elif pat[i] == "*":
            out += "[^/]*"; i += 1
        elif pat[i] == "?":
            out += "[^/]"; i += 1
        else:
            out += re.escape(pat[i]); i += 1
    return re.compile(out + r"\Z", re.I)


@lru_cache(maxsize=None)
def _rules(repo_path: str) -> tuple[tuple[str, re.Pattern, str], ...]:
    try:
        fm = json.loads(Path(repo_path, "docfx.json").read_text(encoding="utf-8-sig"))["build"]["fileMetadata"]
    except (OSError, ValueError, KeyError, TypeError):
        return ()
    rules = []
    for key in KEYS:
        for pat, val in (fm.get(key) or {}).items():
            if isinstance(val, str):
                rules.append((key, _glob(pat), val))
    return tuple(rules)


def file_metadata(repo_path: Path, rel_path: str) -> dict[str, str]:
    """Values docfx.json assigns to `rel_path` (relative to the repo root); the last matching rule wins, as in docfx."""
    out: dict[str, str] = {}
    for key, rx, val in _rules(str(repo_path)):
        if rx.match(rel_path):
            out[key] = val
    return out
