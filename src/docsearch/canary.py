"""Known-answer queries that must keep working after an update (design 9.2)."""
from __future__ import annotations

import tomllib
from pathlib import Path

from .config import load_config
from .embed import QUERY_PREFIX, Embedder, EmbedServer
from .evalrun import HERE, load_questions
from .search import Searcher


def run_canaries(db_path: Path, path: Path = HERE / "canaries.toml") -> list[str]:
    """Return a list of problems (empty = fine). Uses the eval questions listed in canaries.toml, lenient gold, top-5 pages."""
    spec = tomllib.loads(path.read_text())["canary"]
    qs = {q["id"]: q for q in load_questions(lenient=True)}
    cfg = load_config(HERE / "repos.toml")
    with EmbedServer(port=8098, ctx=4096, parallel=2) as srv:
        emb = Embedder(srv.url, workers=1)
        s = Searcher(db_path, lambda q: emb.embed([q], QUERY_PREFIX)[0], {r.name: r.weight for r in cfg.repos})
        failed = []
        for qid in spec["ids"]:
            q = qs[qid]
            pages = list(dict.fromkeys(h["source"] for h in s.search(q["question"], limit=10, max_tokens=10**6)["hits"]))[:5]
            if not set(pages) & set(q["gold"]):
                failed.append(f"{qid}: {q['question'][:60]!r} -> none of the expected pages in top 5")
    need = spec.get("min_pass", 0.85)
    ok = 1 - len(failed) / len(spec["ids"])
    return [f"canary pass rate {ok:.0%} < {need:.0%}: " + "; ".join(failed)] if ok < need else []
