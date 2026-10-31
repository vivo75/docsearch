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
    u = sub.add_parser("update", help="incremental update from git changes (copy, patch, verify, atomic swap)")
    u.add_argument("--config", default=str(HERE / "repos.toml"))
    u.add_argument("--out", type=Path, default=HERE / "data")
    u.add_argument("--pull", action="store_true", help="git pull --ff-only every repo first")
    u.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    u.add_argument("--force", action="store_true", help="publish even if health checks fail")
    u.add_argument("--canary", action="store_true", help="run the canary queries (needs the embedding server) before publishing")
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
    sub.add_parser("serve", help="run the MCP server on stdio")
    s = sub.add_parser("status", help="show metadata of the current index")
    s.add_argument("--db", type=Path, default=HERE / "data" / "current.db")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        from .build import build
        build(a.config, a.out, repos=a.repos.split(",") if a.repos else None, limit=a.limit,
              embed=not a.no_embed, resume=a.resume, prev=a.prev, force=a.force)
    elif a.cmd == "update":
        import json
        from .update import update
        canary = None
        if a.canary:
            from .canary import run_canaries as canary
        print(json.dumps(update(a.config, a.out, do_pull=a.pull, dry_run=a.dry_run, force=a.force, canary=canary), indent=2))
    elif a.cmd == "verify":
        import json
        from .update import verify
        r = verify(a.config, a.db, a.sample)
        print(json.dumps(r, indent=2))
        raise SystemExit(1 if r["mismatches"] else 0)
    elif a.cmd == "serve":
        from .server import main as serve
        serve()
    elif a.cmd == "search":
        import json
        from .config import load_config
        from .search import Filters, Searcher
        from .search import SearchConfig
        from .server import SERVER_CONFIG, _Embeddings, _Reranking
        cfg = load_config(HERE / "repos.toml")
        sr = Searcher(a.db, None if a.no_semantic else _Embeddings(), {r.name: r.weight for r in cfg.repos},
                      SearchConfig() if a.no_rerank else SERVER_CONFIG, None if a.no_rerank else _Reranking("bge-v2-m3-q8"))
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
