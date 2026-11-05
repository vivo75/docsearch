"""Map a reranker's best score to a probability that the corpus answers the query (`confidence` in search results).

One logistic curve per reranker, p = 1 / (1 + exp(-(a * score + b))), fitted by `eval/abstain.py --calibrate` on the qset2 answerable vs
unanswerable questions and stored in calibration.json next to this file. It reflects the mix of the eval set (about 10% unanswerable): read it as
"higher = more likely answerable", not as an absolute probability. Change the reranker, the embedding model or the corpus much and the fit must be redone.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from pathlib import Path

PATH = Path(__file__).with_name("calibration.json")


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x)) if x >= 0 else math.exp(x) / (1 + math.exp(x))


def fit(scores: list[float], answerable: list[bool], iters: int = 50) -> tuple[float, float]:
    """Logistic regression of answerable on one score (Newton-Raphson, tiny ridge for stability). Returns (a, b)."""
    a, b, ridge = 0.0, 0.0, 1e-6
    for _ in range(iters):
        ga = gb = haa = hab = hbb = 0.0
        for s, y in zip(scores, answerable):
            p = sigmoid(a * s + b); r = p - y; w = p * (1 - p) + 1e-12
            ga += r * s; gb += r; haa += w * s * s; hab += w * s; hbb += w
        haa += ridge; hbb += ridge
        det = haa * hbb - hab * hab
        da, db = (hbb * ga - hab * gb) / det, (haa * gb - hab * ga) / det
        a, b = a - da, b - db
        if abs(da) + abs(db) < 1e-10:
            break
    return a, b


def calibrator(reranker: str, path: Path = PATH) -> Callable[[float], float] | None:
    """The score -> probability function for `reranker`, or None if it was never calibrated (then results carry only `rerank_max`)."""
    try:
        c = json.loads(path.read_text())[reranker]
        a, b = float(c["a"]), float(c["b"])
    except (OSError, KeyError, ValueError, TypeError):
        return None
    return lambda score: sigmoid(a * score + b)


def hit_calibrator(reranker: str, path: Path = PATH) -> Callable[[float, int], float] | None:
    """(rerank score, 0-based position among the distinct pages shown) -> probability that this hit is a page a human judged right for the query.
    Fitted by `eval/hit_calibration.py` on qset2 (lenient gold, so it underestimates: a useful page outside the gold set counts as wrong).
    Unlike `confidence` (is the corpus able to answer at all) it tells the good hits from the weak ones inside one answer."""
    try:
        h = json.loads(path.read_text())[reranker]["hit"]
        w0, ws, wr = float(h["w0"]), float(h["w_score"]), float(h["w_rank"])
    except (OSError, KeyError, ValueError, TypeError):
        return None
    return lambda score, rank: sigmoid(w0 + ws * score + wr * math.log1p(rank))
