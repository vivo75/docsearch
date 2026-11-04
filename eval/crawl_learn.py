"""Reconstruct checkouts for doc sources that are private on GitHub from rendered Learn markdown.

Covers MicrosoftDocs/nosql-docs-pr (Cosmos DB, depot Learn.azure-nosql) and
MicrosoftDocs/azure-security-docs-pr (Key Vault, depot Learn.azure-security):
no public mirror exists under any name, so the checkouts are rebuilt from
`?accept=text/markdown`, which carries full frontmatter (ms.service/topic/date,
source_path, monikers) with includes already expanded and zone pivots intact.

Idempotent: only rewrites changed files; `git init` + commit makes the result a
normal checkout for `docsearch update` (pull of a remote-less repo fails loudly
but non-fatally in update.py). Rate: 1 request / 0.8 s.

To keep external traffic low, page downloads are split into 7 stable shards
(sha1 of the slug mod 7) and `--shard auto` fetches only one shard per day
(ISO weekday); the TOC walk (a few small files) still runs every time so
upstream deletions are picked up daily without download cost.

  uv run python eval/crawl_learn.py --service keyvault --areas general   # pilot
  uv run python eval/crawl_learn.py --service all                        # full (first run)
  uv run python eval/crawl_learn.py --service all --shard auto           # daily: 1/7 of the pages
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import posixpath
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parents[1]
SITE = "https://learn.microsoft.com"
LOCALE = "en-us"
RATE = 0.8

SERVICES = {
    "cosmos": {
        "checkout": "nosql-docs",
        # (toc-url-dir, checkout-subdir): toc lists pages under the URL dir,
        # files are written under the checkout subdir (== frontmatter source_path).
        "areas": [("azure/cosmos-db", "azure/cosmos-db")],
        "url_prefix": "azure/cosmos-db/",
        "src_prefix": "azure/cosmos-db/",
        "entry": {"name": "nosql-docs", "docs_root": "azure/cosmos-db",
                  "url_base": "https://learn.microsoft.com/azure/cosmos-db"},
    },
    "keyvault": {
        "checkout": "azure-security-docs",
        "areas": [(f"azure/key-vault/{a}", f"articles/key-vault/{a}")
                  for a in ("general", "keys", "secrets", "certificates", "managed-hsm")],
        "url_prefix": "azure/key-vault/",
        "src_prefix": "articles/key-vault/",
        "entry": {"name": "azure-security-docs", "docs_root": "articles/key-vault",
                  "url_base": "https://learn.microsoft.com/azure/key-vault"},
    },
}

UA = {"User-Agent": "docsearch-corpus-crawl (contact: repo owner; 1 req/0.8s)"}


def get(url: str, tries: int = 4) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                raise
            print(f"    retry {url} ({type(e).__name__})", flush=True)
            time.sleep(2 * (i + 1))


def toc_pages(url_dir: str) -> tuple[list[str], dict]:
    """Page slugs under an area TOC (query/fragments stripped, deduped)."""
    raw = get(f"{SITE}/{LOCALE}/{url_dir}/toc.json")
    time.sleep(RATE)
    toc = json.loads(raw)
    out: list[str] = []

    def walk(n):
        if isinstance(n, dict):
            h = n.get("href")
            if isinstance(h, str) and h and not h.startswith(("http://", "https://", "#")):
                p = posixpath.normpath(posixpath.join(url_dir, h.split("?")[0].split("#")[0]))
                if p == url_dir:
                    pass  # area landing './': the area page itself is fetched separately below
                elif p.startswith(url_dir + "/"):
                    out.append(p)
                # else: cross-depot link (../documentdb/..., /azure/...): not ours
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(toc.get("items", []))
    seen = list(dict.fromkeys(out))
    return seen, toc


def split_md(text: str) -> tuple[dict, str]:
    # Upstream line endings fluctuate between requests (\n, \r\n and mixed);
    # collapse them all up front or every fetch looks like a change.
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    assert text.startswith("---\n"), "no frontmatter"
    end = re.search(r"^(?:---|\.\.\.)[ \t]*$", text[4:], re.M)
    raw, body = text[4:4 + end.start()], text[4 + end.end():].lstrip("\n")
    return yaml.safe_load(raw) or {}, body


SUFFIX = " | Microsoft Learn"


def normalize(meta: dict, body: str) -> tuple[dict, str]:
    import datetime as _dt
    d = meta.get("ms.date")
    if isinstance(d, (_dt.datetime, _dt.date)):   # yaml auto-parses timestamps: pin to YYYY-MM-DD
        meta["ms.date"] = d.strftime("%Y-%m-%d")
    elif isinstance(d, str) and re.match(r"\d{4}-\d{2}-\d{2}", d.strip()):
        meta["ms.date"] = d.strip()[:10]
    t = meta.get("title")
    if isinstance(t, str) and t.strip().endswith(SUFFIX):
        meta["title"] = t.strip()[: -len(SUFFIX)]
    body = re.sub(r"^(#+ .+?)" + re.escape(SUFFIX) + r"([ \t]*)$", r"\1\2", body, flags=re.M)
    return meta, body


def dump(meta: dict, body: str) -> str:
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n\n" + body


def toc_yml(toc: dict, saved: set[str], area_subdir: str) -> list:
    """Mirror the toc.json tree, keeping only branches that contain saved pages.
    saved: checkout-relative paths of written .md files; area_subdir: TOC dir."""

    def conv(items):
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            name = it.get("toc_title") or it.get("displayName") or ""
            kids = conv(it.get("children") or it.get("items") or [])
            h = it.get("href")
            node = {"name": name} if name else {}
            target = None
            if isinstance(h, str) and h and not h.startswith(("http://", "https://", "#")):
                slug = posixpath.normpath(h.split("?")[0].split("#")[0])
                for cand in (slug, slug + ".md"):
                    if posixpath.join(area_subdir, cand) in saved:
                        target = cand if cand.endswith(".md") else cand + ".md"
                        break
                if target is None and not kids and (h.startswith("/") or h.startswith("http")):
                    continue  # external leaf: drop (would be a dead end in browse)
                if target is None and not kids:
                    # subsection landing './' or anchor-only: keep as plain node
                    pass
            if target:
                node["href"] = target
            if kids:
                node["items"] = kids
            if len(node) > (1 if name else 0) or kids:
                out.append(node)
        return out

    return conv(toc.get("items", []))


def shard_of(slug: str, n: int = 7) -> int:
    """Stable shard for a page slug: sha1(slug) mod n. New pages fall into a
    shard by hash, so every page is re-fetched every n runs with no bookkeeping."""
    return int(hashlib.sha1(slug.encode()).hexdigest(), 16) % n


def crawl(service: str, areas: list[str] | None, limit: int | None, shard: int | None) -> dict:
    spec = SERVICES[service]
    root = HERE.parent.parent  # corpus root (repos.toml root is two levels above the config file)
    checkout = root / spec["checkout"]
    checkout.mkdir(exist_ok=True)
    stats = {"pages": 0, "written": 0, "tocs": 0, "skipped": 0, "shard": shard, "deleted": 0, "mismatch": []}
    saved: set[str] = set()
    renamed: list[tuple[str, str]] = []  # (old rel, new rel) when a page moves (e.g. .yml -> .md)
    toc_by_area: dict[str, dict] = {}
    wanted: set[str] = set()  # every page the TOCs list (for deletion detection)
    slugmap: dict[str, str] = {}  # slug -> checkout-relative path, persisted in manifest.json
    mf = checkout / "manifest.json"
    if mf.exists():
        try:
            slugmap = json.loads(mf.read_text(encoding="utf-8")).get("slugs", {})
        except (OSError, ValueError):
            pass
    jobs: list[tuple[str, str]] = []  # (slug, area) to fetch
    for url_dir, subdir in spec["areas"]:
        area = url_dir.rsplit("/", 1)[-1]
        if areas and area not in areas:
            continue
        slugs, toc = toc_pages(url_dir)
        toc_by_area[area] = (subdir, toc)
        # area landing page itself ('./', e.g. /azure/key-vault/general/)
        wanted.update([url_dir] + slugs)
        if limit:
            slugs = slugs[:limit]
        print(f"{service}/{area}: {len(slugs) + 1} pages in TOC", flush=True)
        jobs.extend((s, area) for s in slugs)
    if shard is not None:
        jobs = [(s, a) for s, a in jobs if shard_of(s) == shard]
    print(f"fetching {len(jobs)} pages" + (f" (shard {shard}/7)" if shard is not None else ""), flush=True)
    for slug, area in jobs:
        rel = slug + ".md"  # where we expect it; verified against frontmatter below
        try:
            text = get(f"{SITE}/{LOCALE}/{slug}?accept=text/markdown").decode("utf-8")
        except Exception as e:
            print(f"    FAIL {slug}: {type(e).__name__}", flush=True)
            stats["skipped"] += 1
            continue
        time.sleep(RATE)
        try:
            meta, body = split_md(text)
        except AssertionError:
            print(f"    NO-FRONTMATTER {slug}", flush=True)
            stats["skipped"] += 1
            continue
        sp = meta.get("source_path")
        if isinstance(sp, str) and sp:
            tail = posixpath.normpath(sp)
            yml_source = tail.endswith(".yml")    # FAQ pages: YAML source, markdown body
            if tail.startswith(spec["src_prefix"]):
                tail = tail[len(spec["src_prefix"]):]
            if tail.endswith(".md"):
                tail = tail[:-3]
            want = slug[len(spec["url_prefix"]):] if slug.startswith(spec["url_prefix"]) else slug
            if tail != want and not (yml_source and tail == want + ".yml"):
                stats["mismatch"].append((slug, sp))
            rel = posixpath.normpath(sp)
            if yml_source:
                rel = rel[: -len(".yml")] + ".md"
            old_rel = slugmap.get(slug)
            if old_rel and old_rel != rel:
                renamed.append((old_rel, rel))
        meta, body = normalize(meta, body)
        dest = checkout / rel
        content = dump(meta, body)
        stats["pages"] += 1
        saved.add(rel)
        slugmap[slug] = rel
        # NOTE: read_bytes, not read_text: text-mode universal-newline
        # translation would mask \r differences and defeat the skip.
        if dest.exists():
            try:
                if dest.read_bytes().decode("utf-8") == content:
                    continue
            except (OSError, UnicodeDecodeError):
                pass
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        stats["written"] += 1
    # Explicit renames (e.g. .yml source now saved as .md): drop the old path.
    # Applies on every run: it only touches pages fetched (and rewritten) now.
    if renamed and (checkout / ".git").exists():
        tracked = set(subprocess.run(["git", "-C", str(checkout), "ls-files", "-z"],
                                     capture_output=True, text=True, check=True).stdout.split("\0"))
        for old_rel, _ in renamed:
            if old_rel in tracked and (checkout / old_rel).exists() is False:
                pass  # already gone; the new path is tracked via git add -A below
            elif old_rel in tracked:
                subprocess.run(["git", "-C", str(checkout), "rm", "-q", "--", old_rel], check=True)
                stats["deleted"] = stats.get("deleted", 0) + 1
                print(f"moved {old_rel}", flush=True)
    # Deletion pass (slugmap comes from the previous manifest.json, loaded above):
    # pages that were mapped before but are gone from every TOC walked this run
    # (upstream removals/renames). Only on full-area, un-limited runs: with
    # --areas/--limit the TOC view is partial by design.
    if limit is None and (areas is None or set(areas) >= {a.rsplit("/", 1)[-1] for a, _ in spec["areas"]}):
        gone = sorted({rel for slug, rel in slugmap.items() if slug not in wanted})
        if gone and (checkout / ".git").exists():
            tracked = set(subprocess.run(["git", "-C", str(checkout), "ls-files", "-z"],
                                         capture_output=True, text=True, check=True).stdout.split("\0"))
            doomed = sorted(r for r in gone if r in tracked)
            if doomed:
                subprocess.run(["git", "-C", str(checkout), "rm", "-q", "--", *doomed], check=True)
                stats["deleted"] = len(doomed)
                print(f"deleted {len(doomed)} upstream-removed pages", flush=True)
                for slug in [s for s, r in slugmap.items() if r in set(doomed)]:
                    del slugmap[slug]
    # TOC.yml for the area (against ALL known pages, not just this run's shard,
    # or a sharded run would prune the TOC down to its seventh)
    for area, (subdir, toc) in toc_by_area.items():
        yml = toc_yml(toc, set(slugmap.values()) | saved, subdir)
        data = {"items": yml} if yml else {}
        tp = checkout / subdir / "TOC.yml"
        txt = yaml.safe_dump(data, allow_unicode=True, sort_keys=False) if data else ""
        old = tp.read_text(encoding="utf-8") if tp.exists() else None
        if txt != (old or ""):
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text(txt, encoding="utf-8")
        stats["tocs"] += 1
    (checkout / "manifest.json").write_text(json.dumps(
        {"method": "rendered Learn markdown (?accept=text/markdown), 1 req/0.8s",
         "schedule": "1/7 of the pages per day by sha1(slug) mod 7 (ISO weekday); TOC walk every run",
         "sources": ["MicrosoftDocs/nosql-docs-pr", "MicrosoftDocs/azure-security-docs-pr"][0 if service == "cosmos" else 1],
         "date": time.strftime("%Y-%m-%d"), "slugs": slugmap, **stats}, indent=1) + "\n", encoding="utf-8")
    (checkout / ".gitignore").write_text("RECONSTRUCTED.md\nmanifest.json\n", encoding="utf-8")
    (checkout / "RECONSTRUCTED.md").write_text(
        f"# {spec['checkout']}: NOT the real repository\n\n"
        f"This directory is a stand-in rebuilt from rendered Microsoft Learn pages "
        f"(`?accept=text/markdown`, {time.strftime('%Y-%m-%d')}); the real sources "
        f"(`{['MicrosoftDocs/nosql-docs-pr', 'MicrosoftDocs/azure-security-docs-pr'][0 if service == 'cosmos' else 1]}`) "
        f"are private. Text is best-effort: exact markup, tab/zone edge cases and link URLs may differ from the "
        f"originals. Each file keeps its Learn frontmatter (ms.service/topic/date, source_path). "
        f"Frontmatter `ms.date` is truncated to YYYY-MM-DD and the ` | Microsoft Learn` title suffix is stripped. "
        f"Delete this directory to undo; if the real repo is ever cloned here, replace the directory and run `docsearch build`.\n",
        encoding="utf-8")
    # git init + commit so `docsearch update` treats it like any checkout
    if not (checkout / ".git").exists():
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    subprocess.run(["git", "-C", str(checkout), "add", "-A"], check=True)
    dirty = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain"],
                           capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        msg = f"crawl {time.strftime('%Y-%m-%d')}: {stats['written']} written"
        if stats.get("deleted"):
            msg += f", {stats['deleted']} deleted"
        if shard is not None:
            msg += f" (shard {shard}/7)"
        subprocess.run(["git", "-C", str(checkout), "commit", "-qm", msg], check=True)
        print("committed", flush=True)
    else:
        print("no changes", flush=True)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--service", choices=["cosmos", "keyvault", "all"], required=True)
    ap.add_argument("--areas", help="comma-separated area names (default: all)")
    ap.add_argument("--limit", type=int, help="max pages per area (pilot)")
    ap.add_argument("--shard", default="all",
                    help="'auto' (= ISO weekday, for the nightly run), 0-6, or 'all' (default: full crawl)")
    a = ap.parse_args()
    areas = a.areas.split(",") if a.areas else None
    if a.shard == "auto":
        shard: int | None = datetime.date.today().isoweekday() % 7
    elif a.shard == "all":
        shard = None
    else:
        shard = int(a.shard)
        assert 0 <= shard <= 6
    svcs = ["cosmos", "keyvault"] if a.service == "all" else [a.service]
    total = {}
    for s in svcs:
        total[s] = crawl(s, areas, a.limit, shard)
    print(json.dumps(total, indent=1))


if __name__ == "__main__":
    main()
