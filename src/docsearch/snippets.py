"""Code-snippet directives (design 4.3): `:::code` and legacy `[!code-lang[name](path#tag)]`."""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

_CODE_BLOCK = re.compile(r"^(\s*):{3,}\s*code\b(.*?)(?::{3,})?\s*$")
_LEGACY = re.compile(r"^(\s*)\[!code-([\w+#.-]*)\s*\[[^\]]*\]\(([^)]*)\)\]\s*$", re.I)
_ATTR = re.compile(r"([\w-]+)\s*=\s*\"([^\"]*)\"")
_MARKER = re.compile(
    r"^\s*(?://|#|--|'|;|%|/\*|<!--)\s*</?[A-Za-z_][\w.-]*>\s*(?:\*/|-->)?\s*$"
    r"|^\s*(?://|#)\s*(?:end)?region\b.*$",
    re.I,
)
_LANG_ALIAS = {"azurecli": "azurecli", "azure-cli": "azurecli", "cs": "csharp", "js": "javascript", "ts": "typescript"}


@dataclass
class SnippetRef:
    indent: str
    source: str
    language: str = ""
    range: str = ""
    id: str = ""


def parse_directive(line: str) -> SnippetRef | None:
    m = _CODE_BLOCK.match(line)
    if m:
        a = dict(_ATTR.findall(m.group(2)))
        if "source" not in a:
            return None
        return SnippetRef(m.group(1), a["source"], a.get("language", ""), a.get("range", ""), a.get("id", ""))
    m = _LEGACY.match(line)
    if m:
        inner = re.sub(r'\s+"[^"]*"\s*$', "", m.group(3).strip())
        path, _, frag = inner.partition("#")
        query = ""
        if "?" in path:
            path, query = path.split("?", 1)
        elif "?" in frag:
            frag, query = frag.split("?", 1)
        q = dict(kv.split("=", 1) for kv in re.split(r"[&;]", query) if "=" in kv)
        lang = m.group(2).split("#")[0]
        return SnippetRef(m.group(1), path, lang, q.get("range", ""), q.get("id", "") or frag)
    return None


def _parse_ranges(spec: str, n: int) -> list[tuple[int, int]]:
    out = []
    for part in spec.split(","):
        part = part.strip().upper().replace("L", "")
        if not part:
            continue
        a, dash, b = part.partition("-")
        lo = int(a) if a else 1
        hi = (int(b) if b else n) if dash else lo
        out.append((max(1, lo), min(n, hi)))
    return out


def _region(lines: list[str], tag: str) -> list[str] | None:
    t = re.escape(tag)
    start = re.compile(rf"<\s*{t}\s*>|#\s*region\s+{t}\b", re.I)
    for i, ln in enumerate(lines):
        if not start.search(ln):
            continue
        if re.search(r"region", ln, re.I):
            depth = 0
            for j in range(i, len(lines)):
                if re.match(r"\s*#\s*region\b", lines[j], re.I):
                    depth += 1
                elif re.match(r"\s*#\s*endregion\b", lines[j], re.I):
                    depth -= 1
                    if depth == 0:
                        return lines[i + 1 : j]
            return lines[i + 1 :]
        end = re.compile(rf"</\s*{t}\s*>", re.I)
        for j in range(i + 1, len(lines)):
            if end.search(lines[j]):
                return lines[i + 1 : j]
        return lines[i + 1 :]
    return None


def select(text: str, ref: SnippetRef) -> str | None:
    """Apply id/range selectors; None when the requested region/range cannot be found."""
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if ref.id:
        lines = _region(lines, ref.id)
        if lines is None:
            return None
    elif ref.range:
        try:
            rs = _parse_ranges(ref.range, len(lines))
        except ValueError:
            return None
        lines = [l for lo, hi in rs for l in lines[lo - 1 : hi]]
    lines = [l for l in lines if not _MARKER.match(l)]
    return textwrap.dedent("\n".join(lines)).strip("\n")


def fence(code: str, lang: str, indent: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", code)), default=0)
    f = "`" * max(3, longest + 1)
    body = "\n".join(indent + l if l else l for l in code.split("\n"))
    return f"{indent}{f}{lang}\n{body}\n{indent}{f}"


def render(ref: SnippetRef, source: Path) -> str | None:
    try:
        text = source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    code = select(text, ref)
    if code is None:
        return None
    lang = _LANG_ALIAS.get(ref.language.lower(), ref.language.lower())
    return fence(code, lang, ref.indent)
