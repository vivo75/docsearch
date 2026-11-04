"""Rank distance of candidate pages for one question (server config, live index).

Answers "how far is page X for question Y": prints the top-N hits with
rerank scores and the rank of each candidate source. Used to judge whether a
page is a legitimate also_ok gold (ranks nearby but outside the top 5) or
genuinely unretrievable.

Run from the project root:

    uv run python eval/examples/rank_distance.py \\
        "How do I give someone read-only access to a resource group?" \\
        azure-docs/articles/role-based-access-control/built-in-roles.md \\
        azure-docs/articles/role-based-access-control/built-in-roles/general.md

With no arguments it runs the q013 case this was written for.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from docsearch.config import load_config
from docsearch.embed import Embedder, QwenServer, qwen_query
from docsearch.expand import QueryExpander
from docsearch.rerank import Reranker, RerankServer
from docsearch.server import SERVER_CONFIG

HERE = Path(__file__).resolve().parents[2]

Q013 = "How do I give someone read-only access to a resource group?"
Q013_CANDS = [
    "azure-docs/articles/role-based-access-control/built-in-roles.md",
    "azure-docs/articles/role-based-access-control/built-in-roles/general.md",
    "azure-docs/articles/role-based-access-control/role-assignments-portal.md",
    "azure-docs/articles/role-based-access-control/tutorial-role-assignments-group-powershell.md",
]


def main() -> None:
    question = sys.argv[1] if len(sys.argv) > 1 else Q013
    cands = sys.argv[2:] if len(sys.argv) > 2 else Q013_CANDS
    H = Path(".").resolve()
    cfg = load_config(H / "repos.toml")
    ex = QueryExpander("", H / "eval/qset2/expansions.json")
    if question not in ex.cache:
        print(f"no cached expansion for {question!r}; run eval/qset2.py pool or compare first")
        sys.exit(2)

    with QwenServer("4b") as qsv:
        emb = Embedder(qsv.url, workers=1)
        memo = {t: emb.embed([qwen_query(t)], "")[0] for t in (question, question + " " + ex.cache[question])}
        with RerankServer("bge-v2-m3-q8") as rs:
            rr = Reranker(rs.url, "bge-v2-m3-q8")
            from docsearch.search import Searcher
            s = Searcher(H / "data/current.db", memo.__getitem__,
                         {r.name: r.weight for r in cfg.repos},
                         replace(SERVER_CONFIG, expand_vec=1.0),
                         lambda qq, d: rr.score(qq, d), lambda qq: ex.cache[qq])
            res = s.search(question, limit=50, max_tokens=10 ** 6)
            print("warnings:", res.get("warnings"))
            pages = [h["source"] for h in res["hits"]]
            for i, h in enumerate(res["hits"][:12], 1):
                print(f"    {i:2d}. {h['source']} rerank_score={h.get('rerank_score', '-')}")
            print("distances:")
            for c in cands:
                print(f"    {c}: rank={[i + 1 for i, p in enumerate(pages) if p == c] or None}")


if __name__ == "__main__":
    main()
