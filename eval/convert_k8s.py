"""Kubernetes upstream docs (kubernetes/website) -> a checkout docsearch can index.

    python eval/convert_k8s.py [--pull]

Source: sparse shallow clone `../kubernetes-website` (content/en/docs/{concepts,tasks}, docs/reference/using-api, releases, blog/_posts, examples, hugo.toml).
Selected: docs/concepts, docs/tasks, the API deprecation guide and the other using-api pages, releases/*, and the blog posts that announce a release
(`*-release`, since 2023) or a deprecation/removal (since 2022). Not selected: docs/reference (generated API/kubectl pages, 11 MB of noise), other blog posts.
Output: ../kubernetes-docs/ laid out like kubernetes.io URLs (`_index.md` -> `index.md`; blog posts at blog/YYYY/MM/DD/<slug>.md), so docsearch derives the real URL.
Hugo shortcodes are rewritten to plain Markdown (notes -> blockquotes, include/code_sample expanded from the files, tabs -> bold labels, glossary_tooltip -> its text,
feature-state -> "FEATURE STATE: ...", skew/param from hugo.toml); dynamic release tables (release-data, eol-releases) are dropped. Hugo itself is not needed.
Deterministic and idempotent; commits only on change."""
import argparse, re, subprocess, sys, tomllib
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "kubernetes-website"
OUT = ROOT / "kubernetes-docs"
EN = SRC / "content" / "en"
HEADINGS = {"prerequisites": "Before you begin", "whatsnext": "What's next", "objectives": "Objectives", "cleanup": "Cleaning up", "seealso": "See also",
            "discussion": "Discussion", "synopsis": "Synopsis", "options": "Options", "lessoncontent": "Lesson content", "heading": "Heading"}
TOPIC = {"concept": "concept-article", "task": "how-to", "tutorial": "tutorial", "reference": "reference", "snippet": "article"}
FM = re.compile(r"\A---\n(.*?)\n---[ \t]*\n", re.S)
DEPR = re.compile(r"deprecat|remov|retire|end of life|eol|sunset", re.I)


def versions() -> dict:
    t = tomllib.loads((SRC / "hugo.toml").read_text(encoding="utf-8"))
    p = t.get("params", {})
    latest = str(p.get("latest") or p.get("version") or "v1.0")
    major, minor = (int(x) for x in latest.lstrip("v").split(".")[:2])
    return {"params": p, "major": major, "minor": minor}


V = versions()


def ver(add: int = 0) -> str:
    return f"v{V['major']}.{V['minor'] + add}"


def skew(arg: str) -> str:
    a = arg.split()
    if not a: return ""
    k = a[0]
    if k in ("currentVersion", "latestVersion"): return ver()
    if k == "prevMinorVersion": return ver(-1)
    if k == "oldestMinorVersion": return ver(-2)
    if k == "nextMinorVersion": return ver(1)
    if k == "currentPatchVersion": return ver() + ".0"
    if k == "currentVersionAddMinor" and len(a) > 1:
        try: return ver(int(a[1]))
        except ValueError: return ""
    return ""


def fence(path: Path, lang: str | None = None) -> str:
    if not path.is_file(): return ""
    lang = lang or {"yaml": "yaml", "yml": "yaml", "json": "json", "sh": "bash", "go": "go", "py": "python", "txt": ""}.get(path.suffix.lstrip("."), "")
    return f"```{lang}\n{path.read_text(encoding='utf-8').rstrip()}\n```"


def attr(s: str, name: str) -> str | None:
    m = re.search(rf'{name}\s*=\s*"([^"]*)"', s)
    return m.group(1) if m else None


def render(text: str, page: Path, depth: int = 0) -> str:
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    def include(m):
        f = (page.parent / m.group(1).strip().strip('"'))
        if depth < 4 and f.is_file():
            body = FM.sub("", f.read_text(encoding="utf-8"))
            return render(body, f, depth + 1)
        return ""
    text = re.sub(r'\{\{[<%]\s*include\s+"([^"]+)"\s*[>%]\}\}', include, text)
    def tabinc(m):
        f = page.parent / m.group(2)
        return f"**{m.group(1)}**\n\n" + (render(FM.sub("", f.read_text(encoding='utf-8')), f, depth + 1) if depth < 4 and f.is_file() else "")
    text = re.sub(r'\{\{[<%]\s*tab\s+name="([^"]*)"[^}]*include="([^"]+)"[^}]*/\s*[>%]\}\}', tabinc, text)
    text = re.sub(r'\{\{[<%]\s*code_sample\s+([^}]*?)\s*[>%]\}\}', lambda m: fence(EN / "examples" / (attr(m.group(1), "file") or "_missing_"), attr(m.group(1), "language")), text)
    text = re.sub(r'\{\{[<%]\s*codenew\s+([^}]*?)\s*[>%]\}\}', lambda m: fence(EN / "examples" / (attr(m.group(1), "file") or "_missing_"), attr(m.group(1), "language")), text)
    text = re.sub(r'\{\{[<%]\s*tab\s+name="([^"]*)"[^}]*[>%]\}\}', r"\n**\1**\n", text)
    text = re.sub(r'\{\{[<%]\s*heading\s+"([^"]*)"\s*[>%]\}\}', lambda m: HEADINGS.get(m.group(1), m.group(1)), text)
    def fs(m):
        a = m.group(1)
        if (g := attr(a, "feature_gate_name")): return f"**FEATURE STATE:** feature gate `{g}`"
        return f"**FEATURE STATE:** `Kubernetes {attr(a, 'for_k8s_version') or ''} [{attr(a, 'state') or ''}]`"
    text = re.sub(r'\{\{[<%]\s*feature-state\s+([^}]*?)\s*[>%]\}\}', fs, text)
    text = re.sub(r'\{\{[<%]\s*glossary_tooltip\s+([^}]*?)\s*[>%]\}\}', lambda m: attr(m.group(1), "text") or attr(m.group(1), "term_id") or "", text)
    text = re.sub(r'\{\{[<%]\s*skew\s+([^}]*?)\s*[>%]\}\}', lambda m: skew(m.group(1)), text)
    text = re.sub(r'\{\{[<%]\s*param\s+"([^"]*)"\s*[>%]\}\}', lambda m: str(V["params"].get(m.group(1), "")), text)
    def note(m):
        label = {"note": "Note", "caution": "Caution", "warning": "Warning", "tip": "Tip", "alert": "Note"}[m.group(1)]
        inner = m.group(2).strip().splitlines()
        return "\n> **" + label + ":** " + inner[0] + "".join("\n> " + ln for ln in inner[1:]) + "\n" if inner else ""
    text = re.sub(r'\{\{[<%]\s*(note|caution|warning|tip|alert)\b[^}]*[>%]\}\}(.*?)\{\{[<%]\s*/\1\s*[>%]\}\}', note, text, flags=re.S)
    text = re.sub(r'\{\{[<%]\s*(?:version-check|glossary_definition|api-reference|release-data|eol-releases|upcoming-releases|legacy-repos-deprecation|youtube|figure|mermaid|pageinfo|thirdparty-content)\b[^}]*[>%]\}\}', "", text)
    text = re.sub(r'\{\{[<%]\s*/?\s*[\w-]+[^}]*[>%]\}\}', "", text)         # whatever is left: paired wrappers (tabs, table, example...) keep their content
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def page(src: Path, dst: str, extra: dict) -> tuple[str, str] | None:
    raw = src.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = FM.match(raw)
    meta = (yaml.safe_load(m.group(1)) or {}) if m else {}
    if not isinstance(meta, dict) or not meta.get("title"): return None
    body = render(raw[m.end():] if m else raw, src)
    out = {"title": str(meta["title"]).strip(), "description": " ".join(str(meta.get("description") or "").split()), "ms.service": "kubernetes",
           "ms.topic": extra.get("topic") or TOPIC.get(str(meta.get("content_type", "")), "article")}
    if extra.get("date"): out["ms.date"] = extra["date"]
    return dst, "---\n" + yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=10**6) + "---\n\n# " + out["title"] + "\n\n" + body


def want() -> dict[str, str]:
    res: dict[str, str] = {}
    def add(src: Path, dst: str, **extra):
        if (r := page(src, dst, extra)): res[r[0]] = r[1]
    def docdst(p: Path) -> str:
        rel = p.relative_to(EN).as_posix()
        return re.sub(r"(^|/)_index\.md$", r"\1index.md", rel)
    for sub in ("docs/concepts", "docs/tasks"):
        for p in sorted((EN / sub).rglob("*.md")):
            add(p, docdst(p))
    for p in sorted((EN / "docs/reference/using-api").glob("*.md")) + sorted((EN / "releases").glob("*.md")):
        add(p, docdst(p))
    for p in sorted((EN / "blog/_posts").rglob("*.md")):
        raw = p.read_text(encoding="utf-8")
        m = FM.match(raw.replace("\r\n", "\n"))
        meta = (yaml.safe_load(m.group(1)) or {}) if m else {}
        if not isinstance(meta, dict) or not meta.get("date"): continue
        d = str(meta["date"])[:10]
        slug = str(meta.get("slug") or (p.parent.name if p.name == "index.md" else p.stem))
        title = str(meta.get("title", ""))
        release = slug.endswith("-release") and d >= "2023-01-01"
        if release or (DEPR.search(title) and d >= "2022-01-01"):
            y, mo, dd = d.split("-")
            add(p, f"blog/{y}/{mo}/{dd}/{slug}.md", date=d, topic="blog")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--pull", action="store_true")
    a = ap.parse_args()
    if a.pull:
        subprocess.run(["git", "-C", str(SRC), "pull", "-q", "--ff-only"], check=True)
    if not EN.is_dir():
        sys.exit(f"{EN} missing: see the docstring (sparse clone of kubernetes/website)")
    files = want()
    OUT.mkdir(exist_ok=True)
    written = removed = 0
    for rel, content in files.items():
        p = OUT / rel
        if p.exists() and p.read_text(encoding="utf-8") == content: continue
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8"); written += 1
    for p in OUT.rglob("*.md"):
        if p.relative_to(OUT).as_posix() not in files and p.name != "README.md":
            p.unlink(); removed += 1
    (OUT / "README.md").write_text("# kubernetes-docs: NOT the website repository\n\nConverted from kubernetes/website by `docsearch/eval/convert_k8s.py` (Hugo shortcodes rewritten).\n", encoding="utf-8")
    if not (OUT / ".git").exists():
        subprocess.run(["git", "init", "-q", str(OUT)], check=True)
    subprocess.run(["git", "-C", str(OUT), "add", "-A"], check=True)
    dirty = subprocess.run(["git", "-C", str(OUT), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        subprocess.run(["git", "-C", str(OUT), "commit", "-qm", f"convert: {written} written, {removed} removed"], check=True)
    print(f"{len(files)} pages: {written} written, {removed} removed" + ("" if dirty else " (no changes)"))


main()
