"""Evaluation harness (design 10): score retrieval systems on eval/questions.jsonl.

Systems: docsearch (any SearchConfig), grep-proxy (Option 1 without an agent loop), learn-mcp (Option 0).
Gold labels are page-level `repo/path` sources; a question is a hit at rank r if the r-th distinct page is gold.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import statistics
import subprocess
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path

from . import store
from .chunker import count_tokens
from .config import Config, load_config
from .search import Filters, SearchConfig, Searcher, parse_query, near_duplicate, shingles
from .urls import normalize_url
from .variants import variant_matches

HERE = Path(__file__).resolve().parents[2]
CUT = 20


def load_questions(path: Path = HERE / "eval" / "questions.jsonl", lenient: bool = False) -> list[dict]:
    """lenient=True adds the pooled judgments in eval/judgments.json to each question's gold set."""
    qs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    if lenient:
        j = json.loads((path.parent / "judgments.json").read_text())
        for q in qs:
            q["gold"] = sorted({*q["gold"], *j.get(q["id"], {}).get("also_ok", [])})
    return qs


# ---------------------------------------------------------------- systems: each returns ranked sources + extras
class DocsearchSystem:
    def __init__(self, db: Path, embed, cfg: Config, config: SearchConfig, name: str = "docsearch", measure: bool = True,
                 reranker=None, expander=None, credit_also_in: bool = False, extras: dict[str, list[str]] | None = None):
        self.name, self.measure, self.credit = name, measure, credit_also_in
        self.extras = extras or {}                      # question id -> extra queries (what a calling agent would add)
        self.s = Searcher(db, embed, {r.name: r.weight for r in cfg.repos}, config, reranker, expander)
        self.db = self.s.db

    def _variant_filter(self, q: dict) -> Filters | None:
        ev = q.get("expected_variant")
        if not ev:
            return None
        col = self.db.execute("SELECT count(*) FROM chunks WHERE variant_pivot LIKE ?", (f"%{ev}%",)).fetchone()[0]
        return Filters(pivot=ev) if col else Filters(tab=ev)

    def run(self, q: dict, filtered: bool = False) -> dict:
        f = self._variant_filter(q) if filtered else None
        t = time.perf_counter()
        wide = self.s.search(q["question"], f, limit=CUT, max_tokens=10**6, extra_queries=self.extras.get(q["id"]))
        latency = (time.perf_counter() - t) * 1000
        tokens = 0
        if self.measure:                                       # what an agent actually receives by default
            default = self.s.search(q["question"], f, extra_queries=self.extras.get(q["id"]))
            tokens = sum(count_tokens(h["snippet"]) for h in default["hits"])
        ranked, seen = [], set()
        for h in wide["hits"]:
            if h["source"] not in seen:
                seen.add(h["source"]); ranked.append((h["source"], h))
        sig = [shingles(h["snippet"]) for _, h in ranked[:10]]
        dup10 = sum(any(near_duplicate(sig[i], sig[j], 0.8) for j in range(i)) for i in range(len(sig)))   # near-copies among the 10 shown hits
        sources = [s for s, _ in ranked]
        if self.credit:                       # the answer lists `also_in` pages: count them as found at the representative's rank
            sources, seen = [], set()
            for s, h in ranked:
                for x in [s, *[a["source"] for a in h.get("also_in", [])]]:
                    if x not in seen:
                        seen.add(x); sources.append(x)
        return {"ranked": sources, "hits": [h for _, h in ranked], "dup10": dup10,
                "top_score": wide.get("rerank_max", wide["hits"][0]["score"] if wide["hits"] else 0.0),
                "tokens": tokens, "latency_ms": latency}


class GrepProxySystem:
    """Option 1 without the agent loop: rank files by idf-weighted count of distinct question terms found by ripgrep."""
    name = "grep-proxy"

    def __init__(self, cfg: Config):
        self.root, self.cfg = cfg.root.resolve(), cfg
        self.roots = [r.rel_dir(self.root) for r in cfg.checkouts()]     # a shared checkout once
        self.n_files = 22000

    def _files(self, term: str) -> set[str]:
        p = subprocess.run(["rg", "-l", "-i", "-F", "--glob", "*.md", "-e", term, "--", *self.roots],
                           cwd=self.root, capture_output=True, text=True, timeout=60)
        return {self.cfg.source_for(f) or f for f in p.stdout.split()}      # gold ids are <entry name>/<repo path>

    def run(self, q: dict, filtered: bool = False) -> dict:
        t0 = time.perf_counter()
        terms = list(dict.fromkeys(parse_query(q["question"]).terms + [i for i in parse_query(q["question"]).idents]))[:8]
        score: dict[str, float] = defaultdict(float)
        for term in terms:
            files = self._files(term)
            if files:
                w = math.log(self.n_files / len(files))
                for f in files:
                    score[f] += w
        ranked = sorted(score, key=score.get, reverse=True)[:CUT]
        top = score[ranked[0]] if ranked else 0.0
        return {"ranked": ranked, "hits": [], "top_score": top, "tokens": 0,
                "latency_ms": (time.perf_counter() - t0) * 1000}


class LearnMcpSystem:
    """Option 0: the hosted Microsoft Learn MCP server (public, read-only). Results are mapped to corpus sources by URL."""
    name = "learn-mcp"
    URL = "https://learn.microsoft.com/api/mcp"

    def __init__(self, db: Path):
        d = store.connect(db, readonly=True)
        self.by_url = {normalize_url(u): f"{r}/{p}" for u, r, p in d.execute("SELECT url, repo, path FROM docs WHERE url IS NOT NULL")}
        self.redirects = dict(d.execute("SELECT old_url, new_url FROM redirects"))
        self.cache_path = HERE / "eval" / "results" / "learn_mcp_cache.json"
        self.cache = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}

    async def _search(self, queries: list[str]) -> dict[str, dict]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        out = {}
        async with streamable_http_client(self.URL) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                for q in queries:
                    t = time.perf_counter()
                    r = await s.call_tool("microsoft_docs_search", {"query": q})
                    text = "".join(getattr(c, "text", "") for c in r.content)
                    out[q] = {"text": text, "ms": (time.perf_counter() - t) * 1000, "error": r.is_error}
        return out

    def prefetch(self, questions: list[dict]) -> None:
        todo = [q["question"] for q in questions if q["question"] not in self.cache]
        if todo:
            self.cache.update(asyncio.run(self._search(todo)))
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache))

    def run(self, q: dict, filtered: bool = False) -> dict:
        c = self.cache[q["question"]]
        urls = list(dict.fromkeys(re.findall(r"https://learn\.microsoft\.com/[^\s\"')>\]]+", c["text"].replace("\\/", "/"))))
        ranked, seen = [], set()
        for u in urls:
            n = normalize_url(u.split("#")[0].split("?")[0])
            for _ in range(5):
                if n in self.by_url or n not in self.redirects:
                    break
                n = self.redirects[n]
            src = self.by_url.get(n, "external:" + n)           # pages outside our corpus still occupy a rank
            if src not in seen:
                seen.add(src); ranked.append(src)
        return {"ranked": ranked[:CUT], "hits": [], "top_score": 0.0,
                "tokens": count_tokens(c["text"]), "latency_ms": c["ms"]}


# ---------------------------------------------------------------- metrics
def rank_of_first(ranked: list[str], gold: set[str]) -> int | None:
    return next((i + 1 for i, s in enumerate(ranked[:CUT]) if s in gold), None)


def score_question(q: dict, res: dict) -> dict:
    gold = set(q["gold"])
    r = rank_of_first(res["ranked"], gold)
    top10 = res["ranked"][:10]
    dcg = sum(1 / math.log2(i + 2) for i, s in enumerate(top10) if s in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(gold), 10)))
    out = {"id": q["id"], "category": q["category"], "rank": r, "latency_ms": res["latency_ms"], "tokens": res["tokens"],
           "r1": bool(r and r <= 1), "r5": bool(r and r <= 5), "r10": bool(r and r <= 10),
           "mrr": 1 / r if r else 0.0, "ndcg10": dcg / ideal if ideal else 0.0,
           "coverage10": len(gold & set(top10)) / len(gold) if gold else 0.0, "top_score": res["top_score"], "dup10": res.get("dup10", 0)}
    out["rerank"] = [h.get("rerank_score") for h in res["hits"][:10]]                    # per-hit signals, for confidence studies
    out["svc"] = [(h.get("meta") or {}).get("service") for h in res["hits"][:10]]
    out["hit_ok"] = [h["source"] in gold for h in res["hits"][:10]]
    ev = q.get("expected_variant")
    if ev and res["hits"]:
        best = next((h for h in res["hits"] if h["source"] in gold), None)
        out["variant_ok"] = bool(best and any(variant_matches(e, ev)
                                              for v in best["variants"] for e in v.split(",")))
    return out


def summarize(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["category"] != "unanswerable"]
    m = lambda k, rs: round(statistics.mean(r[k] for r in rs), 3) if rs else None
    lat = sorted(r["latency_ms"] for r in rows)
    s = {"n": len(ans), "R@1": m("r1", ans), "R@5": m("r5", ans), "R@10": m("r10", ans), "MRR": m("mrr", ans),
         "nDCG@10": m("ndcg10", ans), "tokens": round(statistics.median(r["tokens"] for r in ans)) if ans else None,
         "p50_ms": round(lat[len(lat) // 2]), "p95_ms": round(lat[int(len(lat) * 0.95) - 1])}
    s["by_cat"] = {}
    for cat in sorted({r["category"] for r in ans}):
        rs = [r for r in ans if r["category"] == cat]
        s["by_cat"][cat] = {"n": len(rs), "R@5": m("r5", rs), "MRR": m("mrr", rs), **({"cov@10": m("coverage10", rs)} if cat == "multi_page" else {})}
    vs = [r for r in ans if "variant_ok" in r]
    if vs:
        s["variant_acc"] = round(statistics.mean(r["variant_ok"] for r in vs), 3)
    un = [r["top_score"] for r in rows if r["category"] == "unanswerable"]
    an = [r["top_score"] for r in ans]
    if un and an and any(an):   # AUC: P(answerable top score > unanswerable top score)
        wins = sum((a > u) + 0.5 * (a == u) for a in an for u in un)
        s["unans_auc"] = round(wins / (len(an) * len(un)), 3)
    return s


def run_system(system, questions: list[dict], filtered: bool = False, workers: int = 1) -> tuple[dict, list[dict]]:
    if workers > 1:
        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(lambda q: system.run(q, filtered), questions))
    else:
        results = [system.run(q, filtered) for q in questions]
    rows = [score_question(q, r) for q, r in zip(questions, results)]
    return summarize(rows), rows


def fmt_row(name: str, s: dict) -> str:
    g = lambda k: "  –  " if s.get(k) is None else f"{s[k]:.3f}"
    return (f"| {name:34s} | {g('R@1')} | {g('R@5')} | {g('R@10')} | {g('MRR')} | {g('nDCG@10')} | "
            f"{g('variant_acc')} | {g('unans_auc')} | {s['tokens'] or 0:>5} | {s['p50_ms']:>6} |")


HEADER = ("| system / config                    |  R@1  |  R@5  | R@10  |  MRR  |nDCG@10| var.acc| unans.AUC| tokens | p50 ms |\n"
          "|------------------------------------|-------|-------|-------|-------|-------|--------|----------|--------|--------|")
