from __future__ import annotations

import argparse
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="docsearch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="full index build (parse, chunk, embed, verify, swap)")
    b.add_argument("--config", default=str(HERE / "repos.toml"))
    b.add_argument("--out", type=Path, default=HERE / "data")
    b.add_argument("--repos", help="comma-separated repo names")
    b.add_argument("--limit", type=int, help="max pages per repo (smoke tests)")
    b.add_argument("--no-embed", action="store_true")
    b.add_argument("--resume", type=Path, help="continue embedding into an existing .partial file")
    b.add_argument("--prev", type=Path, help="previous index to reuse vectors from (default: current.db)")
    b.add_argument("--force", action="store_true", help="publish even if health checks fail")
    m = sub.add_parser("migrate", help="add the toc table and ISO dates to the current index (copy + atomic swap)")
    m.add_argument("--config", default=str(HERE / "repos.toml"))
    m.add_argument("--out", type=Path, default=HERE / "data")
    v = sub.add_parser("vecmat", help="(re)build the in-memory vector cache (.npy) of an index; searches use it when present")
    v.add_argument("--db", type=Path, default=HERE / "data" / "current.db", help="index file (default: what data/current.db points to)")
    u = sub.add_parser("update", help="incremental update from git changes (copy, patch, verify, atomic swap)")
    u.add_argument("--config", default=str(HERE / "repos.toml"))
    u.add_argument("--out", type=Path, default=HERE / "data")
    u.add_argument("--pull", action="store_true", help="git pull --ff-only every repo first")
    u.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    u.add_argument("--force", action="store_true", help="publish even if health checks fail")
    u.add_argument("--reprocess", help="comma-separated repos to parse again in full although their git HEAD did not move (after a parser/link-resolution change)")
    u.add_argument("--canary", action="store_true", help="run the canary queries (needs the embedding server) before publishing")
    c = sub.add_parser("changes", help="report of what changed in the git repos in the last update (optionally summarised by the local Gemma)")
    c.add_argument("--config", default=str(HERE / "repos.toml"))
    c.add_argument("--db", type=Path, default=HERE / "data" / "current.db")
    c.add_argument("--base", type=Path, help="compare against the heads recorded in this older index instead of prev_head:*")
    c.add_argument("--summarize", action="store_true", help="one-line summaries per area from the local LLM (starts llama-server if needed)")
    c.add_argument("--lang", default="Italian")
    c.add_argument("--port", type=int, default=8105, help="llama-server port for the summaries (own instance, never the MCP's)")
    c.add_argument("--max-seconds", type=float, default=7200, help="time budget for the LLM summaries (default 2 h)")
    c.add_argument("--out", type=Path, help="also write the Markdown report here")
    v = sub.add_parser("verify", help="re-process a random sample of pages and compare with the index")
    v.add_argument("--config", default=str(HERE / "repos.toml"))
    v.add_argument("--db", type=Path, default=HERE / "data" / "current.db")
    v.add_argument("--sample", type=int, default=200)
    q = sub.add_parser("search", help="run a query against the current index (debugging)")
    q.add_argument("query")
    q.add_argument("--db", type=Path, default=HERE / "data" / "current.db")
    q.add_argument("--service"); q.add_argument("--topic"); q.add_argument("--repo")
    q.add_argument("--pivot"); q.add_argument("--tab"); q.add_argument("--limit", type=int, default=8)
    q.add_argument("--no-semantic", action="store_true")
    q.add_argument("--no-rerank", action="store_true")
    sv = sub.add_parser("serve", help="run the MCP server (stdio, or streamable HTTP with --http)")
    sv.add_argument("--http", action="store_true", help="serve streamable HTTP at http://HOST:PORT/mcp instead of stdio (no authentication!)")
    sv.add_argument("--host", default="127.0.0.1", help="address to bind with --http (use the WireGuard interface address, never 0.0.0.0 on an untrusted network)")
    sv.add_argument("--port", type=int, default=8765)
    s = sub.add_parser("status", help="show metadata of the current index")
    s.add_argument("--db", type=Path, default=HERE / "data" / "current.db")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        from .build import build
        build(a.config, a.out, repos=a.repos.split(",") if a.repos else None, limit=a.limit,
              embed=not a.no_embed, resume=a.resume, prev=a.prev, force=a.force)
    elif a.cmd == "vecmat":
        from . import vecmat
        db = a.db.resolve()
        print(f"{db.name}: {vecmat.build(db)} vectors cached")
    elif a.cmd == "update":
        import json
        from .update import update
        canary = None
        if a.canary:
            from .canary import run_canaries as canary
        print(json.dumps(update(a.config, a.out, do_pull=a.pull, dry_run=a.dry_run, force=a.force, canary=canary,
                                reprocess=set(filter(None, (a.reprocess or "").split(",")))), indent=2))
    elif a.cmd == "changes":
        from .changes import run
        from .config import load_config
        print(run(load_config(a.config), a.db, a.base, summ=a.summarize, lang=a.lang, port=a.port, out=a.out,
                  max_seconds=a.max_seconds))
    elif a.cmd == "verify":
        import json
        from .update import verify
        r = verify(a.config, a.db, a.sample)
        print(json.dumps(r, indent=2))
        raise SystemExit(1 if r["mismatches"] else 0)
    elif a.cmd == "serve":
        from .server import main as serve
        serve((a.host, a.port) if a.http else None)
    elif a.cmd == "search":
        import json
        from .config import load_config
        from .search import Filters
        from .server import make_searcher
        sr = make_searcher(a.db, load_config(HERE / "repos.toml"), rerank="off" if a.no_rerank else None,
                           expand=False if a.no_rerank else None, semantic=not a.no_semantic)
        res = sr.search(a.query, Filters(a.service, a.topic, a.repo, a.pivot, a.tab), a.limit)
        for h in res["hits"]:
            print(f"{h['score']:.4f}  {h['url'] or h['source']}\n        {h['heading']}  {h['variants'] or ''}  [{h['meta']['topic']}]")
        print(res["timings"], res["warnings"])
    elif a.cmd == "migrate":
        from .migrate import migrate
        migrate(a.config, a.out)
    else:
        from . import store
        db = store.connect(a.db, readonly=True)
        for k, v in sorted(store.get_meta(db).items()):
            print(f"{k}: {v}")
        for t in ("docs", "chunks", "chunks_vec", "deps", "redirects", "links"):
            print(f"{t}: {db.execute(f'select count(*) from {t}').fetchone()[0]}")
        print("health:", store.health(db) or "ok")
