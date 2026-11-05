"""AKS release notes -> a checkout docsearch can index.

    python eval/convert_aks_releases.py [--pull]

Source: CHANGELOG.md of github.com/Azure/AKS (sparse shallow clone `../AKS`; one `## Release <date>` section per release, ~240 of them).
Output: ../aks-release-notes/releases/tag/<date>.md, one page per release, so that docsearch derives the real GitHub release URL
(https://github.com/azure/aks/releases/tag/<date>) from the path. Frontmatter: title, description (first bullet), ms.date (the release date),
ms.service azure-kubernetes-service, ms.topic release-notes. Deterministic and idempotent; commits only on change."""
import argparse, re, subprocess, sys
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "AKS"
OUT = ROOT / "aks-release-notes"
HEAD = re.compile(r"^## Release(?: Notes)?[ :-]*(\d{4}-\d{1,2}-\d{1,2})(.*)$", re.M)


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--pull", action="store_true")
    a = ap.parse_args()
    if a.pull:
        subprocess.run(["git", "-C", str(SRC), "pull", "-q", "--ff-only"], check=True)
    cl = SRC / "CHANGELOG.md"
    if not cl.exists():
        sys.exit(f"{cl} missing: git clone --depth 1 --filter=blob:none --sparse https://github.com/Azure/AKS.git && git -C AKS sparse-checkout set --no-cone /CHANGELOG.md")
    text = cl.read_text(encoding="utf-8").replace("\r\n", "\n")
    marks = list(HEAD.finditer(text))
    want: dict[str, str] = {}
    for i, m in enumerate(marks):
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)].strip("\n")
        y, mo, d = (int(x) for x in m.group(1).split("-"))
        date = f"{y:04d}-{mo:02d}-{d:02d}"
        suffix = re.sub(r"[^a-z0-9]+", "-", m.group(2).lower()).strip("-")
        slug = m.group(1) + (f"-{suffix}" if m.group(1) + "" in {k.split('/')[-1][:-3] for k in want} else "")
        rel = f"releases/tag/{slug}.md"
        n = 2
        while rel in want:
            rel = f"releases/tag/{slug}-{n}.md"; n += 1
        first = next((ln.lstrip("*- ").strip() for ln in body.splitlines() if ln.strip().startswith(("*", "-")) and len(ln.strip()) > 20), "")
        title = f"AKS release notes {date}" + (f" ({m.group(2).strip(' -()')})" if m.group(2).strip(" -()") else "")
        meta = {"title": title, "description": first[:300], "ms.service": "azure-kubernetes-service", "ms.topic": "release-notes", "ms.date": date}
        want[rel] = "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, width=10**6) + "---\n\n# " + title + "\n\n" + body.rstrip() + "\n"
    OUT.mkdir(exist_ok=True)
    written = removed = 0
    for rel, content in want.items():
        p = OUT / rel
        if p.exists() and p.read_text(encoding="utf-8") == content:
            continue
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text(content, encoding="utf-8"); written += 1
    for p in OUT.rglob("*.md"):
        if p.relative_to(OUT).as_posix() not in want and p.name != "README.md":
            p.unlink(); removed += 1
    (OUT / "README.md").write_text("# aks-release-notes: NOT the AKS repository\n\nSplit per release from CHANGELOG.md of Azure/AKS by `docsearch/eval/convert_aks_releases.py`.\n", encoding="utf-8")
    if not (OUT / ".git").exists():
        subprocess.run(["git", "init", "-q", str(OUT)], check=True)
    subprocess.run(["git", "-C", str(OUT), "add", "-A"], check=True)
    dirty = subprocess.run(["git", "-C", str(OUT), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        subprocess.run(["git", "-C", str(OUT), "commit", "-qm", f"convert: {written} written, {removed} removed"], check=True)
    print(f"{len(want)} releases: {written} written, {removed} removed" + ("" if dirty else " (no changes)"))


main()
