"""Terraform azurerm provider docs -> a checkout docsearch can index.

    python eval/convert_azurerm.py [--pull]

Source: a shallow sparse clone of github.com/hashicorp/terraform-provider-azurerm (`website/docs`, `*.html.markdown`), next to the other corpus repos.
Output: ../azurerm-docs/ (its own local git repo, like the crawled Learn stand-ins) with plain `.md` files laid out like the registry URLs, so that
docsearch derives the public URL from the path:  r/<n>.html.markdown -> resources/<n>.md  (registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/<n>),
d/ -> data-sources/, guides/, functions/, actions/, ephemeral-resources/, list-resources/ keep their name. Frontmatter is rewritten with title, description,
ms.topic (reference for resources/data sources/functions, conceptual for guides) and ms.service `terraform-azurerm`; `subcategory` is kept.
The conversion is deterministic and idempotent: unchanged pages are not rewritten, removed pages are deleted, and a commit is made only on change."""
import argparse, re, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]   # corpus root: the repos are siblings of LLM/
SRC = ROOT / "terraform-provider-azurerm"
OUT = ROOT / "azurerm-docs"
DIRS = {"r": "resources", "d": "data-sources", "guides": "guides", "functions": "functions", "actions": "actions",
        "ephemeral-resources": "ephemeral-resources", "list-resources": "list-resources"}
REFERENCE = {"resources", "data-sources", "functions", "actions", "ephemeral-resources", "list-resources"}
H1 = re.compile(r"^#\s+(.+?)\s*$", re.M)


def convert(path: Path, kind: str) -> str:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    meta, body = {}, text
    m = re.match(r"---\n(.*?)\n---[ \t]*\n", text, re.S)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        body = text[m.end():].lstrip("\n")
    h1 = H1.search(body)
    title = (h1.group(1) if h1 else str(meta.get("page_title", path.name))).strip()
    desc = " ".join(str(meta.get("description") or "").split())
    out = {"title": title, "description": desc, "ms.service": "terraform-azurerm",
           "ms.topic": "reference" if kind in REFERENCE else "conceptual"}
    if meta.get("subcategory"):
        out["subcategory"] = str(meta["subcategory"])
    return "---\n" + yaml.safe_dump(out, allow_unicode=True, sort_keys=False, width=10**6) + "---\n\n" + body.rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--pull", action="store_true", help="fetch the latest provider docs first")
    a = ap.parse_args()
    docs = SRC / "website" / "docs"
    if a.pull:
        subprocess.run(["git", "-C", str(SRC), "fetch", "-q", "--depth", "1", "origin"], check=True)
        subprocess.run(["git", "-C", str(SRC), "reset", "-q", "--hard", "FETCH_HEAD"], check=True)
    if not docs.is_dir():
        sys.exit(f"{docs} missing: git clone --depth 1 --filter=blob:none --sparse https://github.com/hashicorp/terraform-provider-azurerm.git && git sparse-checkout set website/docs")
    want: dict[str, str] = {}
    for f in sorted(docs.rglob("*.html.markdown")):
        rel = f.relative_to(docs)
        stem = f.name[: -len(".html.markdown")]
        if len(rel.parts) == 1:                                   # root: provider index and the version upgrade guides
            dst = "index.md" if stem == "index" else f"guides/{stem}.md"
            kind = "guides"
        else:
            kind = DIRS.get(rel.parts[0])
            if kind is None:
                print("skipped (unknown folder):", rel); continue
            dst = f"{kind}/{'/'.join(rel.parts[1:-1] + (stem,))}.md" if len(rel.parts) > 2 else f"{kind}/{stem}.md"
        want[dst] = convert(f, kind)
    OUT.mkdir(exist_ok=True)
    written = removed = 0
    for rel, content in want.items():
        p = OUT / rel
        if p.exists() and p.read_text(encoding="utf-8") == content:
            continue
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8"); written += 1
    for p in OUT.rglob("*.md"):
        if p.relative_to(OUT).as_posix() not in want:
            p.unlink(); removed += 1
    (OUT / "README.md").write_text("# azurerm-docs: NOT the provider repository\n\nConverted from `website/docs` of hashicorp/terraform-provider-azurerm by `docsearch/eval/convert_azurerm.py`.\n", encoding="utf-8")
    if not (OUT / ".git").exists():
        subprocess.run(["git", "init", "-q", str(OUT)], check=True)
    subprocess.run(["git", "-C", str(OUT), "add", "-A"], check=True)
    dirty = subprocess.run(["git", "-C", str(OUT), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        subprocess.run(["git", "-C", str(OUT), "commit", "-qm", f"convert: {written} written, {removed} removed"], check=True)
    print(f"{len(want)} pages: {written} written, {removed} removed" + ("" if dirty else " (no changes)"))


main()
