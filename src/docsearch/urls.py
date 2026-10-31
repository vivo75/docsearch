"""Canonical URLs, redirects and heading anchors (design 4.6)."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from .config import Config, Repo

SITE = "https://learn.microsoft.com"
_LOCALE = re.compile(r"^/[a-z]{2}-[a-z]{2}(?=/)", re.I)


def doc_url(repo: Repo, rel_path: str) -> str | None:
    """Public Learn URL for a repo-relative source path, or None when unpublished."""
    if not repo.url_base:
        return None
    try:
        sub = (repo.path / rel_path).resolve().relative_to(repo.docs_dir).as_posix()
    except ValueError:
        return None
    sub = re.sub(r"\.(md|yml|json)$", "", sub)
    if sub == "index" or sub.endswith("/index"):
        sub = sub[: -len("index")].rstrip("/")
    return (repo.url_base + ("/" + sub if sub else "")).lower()


def normalize_url(u: str, base: str | None = None) -> str:
    """Absolute, locale-free, lowercase path; query/fragment dropped (kept separately by callers)."""
    parts = urlsplit(u)
    path = parts.path
    if not parts.netloc and not path.startswith("/") and base:
        path = (urlsplit(base).path.rsplit("/", 1)[0] + "/" + path)
        path = re.sub(r"/\./", "/", path)
        while re.search(r"/[^/]+/\.\./", path):
            path = re.sub(r"/[^/]+/\.\./", "/", path, count=1)
    path = _LOCALE.sub("", path).rstrip("/") if path != "/" else path
    host = parts.netloc or urlsplit(SITE).netloc
    return f"https://{host}{path}".lower()


class Redirects:
    def __init__(self) -> None:
        self.map: dict[str, str] = {}

    @classmethod
    def load(cls, repo: Repo) -> "Redirects":
        r = cls()
        for f in sorted(repo.path.glob(".openpublishing.redirection*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            for e in data.get("redirections", []):
                old = doc_url(repo, e.get("source_path", ""))
                new = e.get("redirect_url")
                if old and new:
                    r.map[old] = normalize_url(new, old)
        return r

    def follow(self, url: str, max_hops: int = 5) -> str:
        url = normalize_url(url)
        for _ in range(max_hops):
            nxt = self.map.get(url)
            if not nxt or nxt == url:
                break
            url = nxt
        return url


def slugify(heading: str) -> str:
    """DocFX/Markdig-style heading id: lowercase, spaces -> '-', punctuation removed."""
    h = re.sub(r"`|\*|(?<!\w)_|_(?!\w)|<[^>]+>|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", heading)
    h = unicodedata.normalize("NFKC", h).strip().lower()
    h = re.sub(r"[^\w\- ]", "", h)
    return re.sub(r" ", "-", h)


class Anchors:
    """Per-page unique heading ids (`foo`, `foo-1`, ...)."""

    def __init__(self) -> None:
        self.seen: dict[str, int] = {}

    def make(self, heading: str) -> str:
        s = slugify(heading) or "section"
        n = self.seen.get(s, 0)
        self.seen[s] = n + 1
        return s if n == 0 else f"{s}-{n}"


_EXPLICIT = re.compile(r"""<a\s+[^>]*?(?:name|id)\s*=\s*['"]([^'"]+)['"]""", re.I)


def explicit_anchors(text: str) -> set[str]:
    """Anchors declared by hand: `<a name='x'>` / `<a id="x">` (common in tables of roles, etc.)."""
    return {m.lower() for m in _EXPLICIT.findall(text)}
