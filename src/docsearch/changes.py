"""Report of what changed in the git repositories between two index states, grouped by documentation area.

Needs nothing but git, the two index files and (optionally) a local llama-server running Gemma for one-line summaries;
no external service. The old state comes from `prev_head:<repo>` (written by `update`) or from another index (`base`)."""
from __future__ import annotations

import collections
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import store
from .config import Config, Repo
from .sync import diff, git

PROMPT = ("Below are the changes made to the Microsoft Learn documentation area '{area}' (repository {repo}).\n"
          "Commit titles:\n{commits}\nPages (+ added, ~ modified, - removed):\n{pages}\n\n"
          "Write one or two plain sentences in {lang} saying which topics were changed and how. "
          "Use only what the lists say; do not invent details. Output only the sentences.")


def _group_fn(paths: list[str]):
    """Descend into the single dominant directory (articles/, docs-ref-autogen/Latest-version/latest/...) and group by the next level."""
    prefix = ""
    while True:
        rest = [p[len(prefix):] for p in paths if p.startswith(prefix)]
        kids = collections.Counter(r.split("/", 1)[0] for r in rest if "/" in r)
        if not kids:
            break
        top, n = kids.most_common(1)[0]
        if n < 0.7 * len(paths):
            break
        prefix += top + "/"
    def group(p: str) -> str:
        if not p.startswith(prefix):
            return "(other: " + p.split("/", 1)[0] + ")"
        r = p[len(prefix):]
        return r.split("/", 1)[0] if "/" in r else "(top level)"
    return prefix, group


def collect(cfg: Config, old: dict[str, str], new: dict[str, str], db) -> list[dict]:
    out = []
    for repo in cfg.checkouts():
        names = [r.name for r in cfg.sharing(repo)]
        a = next((old[n] for n in names if old.get(n)), None)
        b = next((new[n] for n in names if new.get(n)), None)
        if not a or not b or a == b:
            continue
        try:
            cs = diff(repo, a, b)
        except subprocess.CalledProcessError:
            out.append({"repo": "/".join(names), "error": "old commit unavailable (shallow clone?)"})
            continue
        state = {p: "+" for p in cs.added} | {p: "~" for p in cs.modified} | {p: "-" for p in cs.deleted}
        state |= {p: "-" for p in cs.renamed} | {p: "+" for p in cs.renamed.values()}
        prefix, group = _group_fn(list(state))
        groups: dict[str, dict] = {}
        for p, s in sorted(state.items()):
            g = groups.setdefault(group(p), {"files": [], "prefix": prefix})
            g["files"].append((s, p))
        for name, g in groups.items():
            paths = [p for _, p in g["files"]]
            titles = {}
            for p in paths[:400]:
                row = db.execute("SELECT title FROM docs WHERE path=? AND repo IN (%s)" % ",".join("?" * len(names)), (p, *names)).fetchone()
                titles[p] = row[0] if row and row[0] else p.rsplit("/", 1)[-1]
            g["titles"] = titles
            spec = [prefix + name] if not name.startswith("(") else paths[:50]
            try:
                subj = git(repo, "log", "--no-merges", "-n", "60", "--format=%s", f"{a}..{b}", "--", *spec).splitlines()
            except subprocess.CalledProcessError:
                subj = []
            g["commits"] = list(dict.fromkeys(s for s in subj if s.strip()))[:12]
        out.append({"repo": "/".join(names), "old": a, "new": b, "groups": groups,
                    "n_commits": _count(repo, a, b), "n_files": len(state)})
    return out


def _count(repo: Repo, a: str, b: str) -> int | None:
    try:
        return int(git(repo, "rev-list", "--count", f"{a}..{b}").strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def summarize(data: list[dict], url: str, lang: str = "English", min_files: int = 1, max_groups: int = 60) -> int:
    """Fill g['summary'] with a short LLM summary for the largest groups. Returns the number of summaries produced."""
    import httpx
    jobs = [(r, n, g) for r in data for n, g in r.get("groups", {}).items() if len(g["files"]) >= min_files]
    jobs.sort(key=lambda j: -len(j[2]["files"]))
    http = httpx.Client(timeout=300)

    def one(job):
        r, n, g = job
        shown = g["files"][:25]
        pages = "\n".join(f"{s} {g['titles'].get(p, p)} ({p.rsplit('/', 1)[-1]})" for s, p in shown)
        if len(g["files"]) > len(shown):
            pages += f"\n... and {len(g['files']) - len(shown)} more"
        commits = "\n".join("- " + c[:160] for c in g["commits"]) or "- (none)"
        try:
            resp = http.post(url + "/v1/chat/completions", json={
                "messages": [{"role": "user", "content": PROMPT.format(area=n, repo=r["repo"], commits=commits, pages=pages, lang=lang)}],
                "max_tokens": 160, "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False}})
            resp.raise_for_status()
            g["summary"] = " ".join(resp.json()["choices"][0]["message"].get("content", "").split())[:600]
        except Exception:
            pass
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(one, jobs[:max_groups]))
    return sum(1 for _, _, g in jobs if g.get("summary"))


def render(data: list[dict], title: str) -> str:
    L = [f"# {title}", ""]
    for r in data:
        if "error" in r:
            L += [f"## {r['repo']}", f"_{r['error']}_", ""]
            continue
        L += [f"## {r['repo']}  ({r['old'][:8]} → {r['new'][:8]})",
              f"{r['n_commits']} commits, {r['n_files']} indexable files touched" if r["n_commits"] is not None
              else f"{r['n_files']} indexable files touched", ""]
        for n, g in sorted(r["groups"].items(), key=lambda kv: -len(kv[1]["files"])):
            c = collections.Counter(s for s, _ in g["files"])
            L.append(f"### {n}: {len(g['files'])} files (+{c['+']} ~{c['~']} -{c['-']})")
            if g.get("summary"):
                L.append(g["summary"])
            else:
                L.append("; ".join(g["commits"][:4]) or "(no commit titles)")
            ex = [g["titles"].get(p, p) for _, p in g["files"][:8]]
            L.append("Pages: " + "; ".join(ex) + (" …" if len(g["files"]) > 8 else ""))
            L.append("")
    return "\n".join(L)


def run(cfg: Config, db_path: Path, base: Path | None, *, summ: bool, lang: str, port: int, out: Path | None) -> str:
    db = store.connect(db_path, readonly=True)
    new = {k[5:]: v for k, v in store.get_meta(db).items() if k.startswith("head:")}
    if base:
        old = {k[5:]: v for k, v in store.get_meta(store.connect(base, readonly=True)).items() if k.startswith("head:")}
    else:
        old = {k[10:]: v for k, v in store.get_meta(db).items() if k.startswith("prev_head:")}
        if not old:
            raise SystemExit("this index has no prev_head:* metadata (built before this feature); pass --base <older index file>")
    data = collect(cfg, old, new, db)
    note = ""
    if summ:
        from .expand import ExpandServer
        try:
            with ExpandServer(port=port) as srv:
                n = summarize(data, srv.url, lang)
            note = f"\n_Summaries by the local LLM ({n} areas); the rest list commit titles._\n"
        except Exception as e:                       # no GPU, no llama-server...: the report is still useful without
            note = f"\n_LLM summaries unavailable ({type(e).__name__}: {e}); commit titles shown instead._\n"
    text = render(data, f"Changes in {db_path.resolve().name}") + note
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    return text
