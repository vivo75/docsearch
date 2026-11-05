"""Fit the per-hit `relevance` curve: P(hit is a gold page) = sigmoid(w0 + w_score*rerank + w_rank*log1p(position)).

    python eval/hit_calibration.py eval/results/<compare-qset2-all>.json [--system live/server] [--write]

Input: a compare.py result with per-hit signals (rows carry `rerank` and `hit_ok`, lenient gold). Prints 5-fold cross-validated AUC / Brier and a
reliability table (grouped by question, so no question is in train and test); --write stores the fit in src/docsearch/calibration.json."""
import argparse, json, time
from pathlib import Path
import numpy as np

CAL = Path(__file__).resolve().parents[1] / "src" / "docsearch" / "calibration.json"


def auc(x, y):
    p, n = x[y == 1], x[y == 0]
    return float((p[:, None] > n[None]).mean() + 0.5 * (p[:, None] == n[None]).mean())


def fit(M, y, it=60):
    w = np.zeros(M.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-M @ w))
        w -= np.linalg.solve((M * (p * (1 - p))[:, None]).T @ M + 1e-3 * np.eye(len(w)), M.T @ (p - y) + 1e-3 * w)
    return w


ap = argparse.ArgumentParser()
ap.add_argument("result", type=Path); ap.add_argument("--system", default="live/server"); ap.add_argument("--reranker", default="bge-v2-m3-q8")
ap.add_argument("--write", action="store_true")
a = ap.parse_args()
rows = [r for r in json.loads(a.result.read_text())["rows"][a.system]["lenient"] if r["category"] != "unanswerable" and r.get("rerank")]
X, Y, G, R = [], [], [], []
for gi, r in enumerate(rows):
    for i, (s, ok) in enumerate(zip(r["rerank"], r["hit_ok"])):
        if s is not None:
            X.append(s); Y.append(ok); G.append(gi); R.append(i)
X, Y, G, R = np.array(X), np.array(Y, float), np.array(G), np.array(R, float)
M = np.column_stack([np.ones(len(X)), X, np.log1p(R)])
fold = np.random.default_rng(0).integers(0, 5, len(rows))[G]
pr = np.zeros(len(X))
for f in range(5):
    tr = fold != f; pr[~tr] = 1 / (1 + np.exp(-M[~tr] @ fit(M[tr], Y[tr])))
print(f"{len(rows)} questions, {len(X)} hits, {Y.mean():.3f} correct; CV AUC {auc(pr, Y):.3f} (own score alone {auc(X, Y):.3f}, -position {auc(-R, Y):.3f}), "
      f"Brier {((pr - Y) ** 2).mean():.4f} (constant {((Y.mean() - Y) ** 2).mean():.4f})")
for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, .9), (.9, 1.01)):
    m = (pr >= lo) & (pr < hi)
    if m.any(): print(f"  predicted {lo:.1f}-{min(hi, 1):.1f}: n={int(m.sum()):4d} mean predicted {pr[m].mean():.2f} observed {Y[m].mean():.2f}")
w = fit(M, Y); print("fit", w.round(4).tolist())
if a.write:
    cal = json.loads(CAL.read_text()); c = cal[a.reranker]
    c["hit"] = {"w0": round(float(w[0]), 4), "w_score": round(float(w[1]), 4), "w_rank": round(float(w[2]), 4), "n_hits": len(X),
                "fitted": time.strftime("%Y-%m-%d"), "set": "qset2 dev+test, lenient gold", "cv_auc": round(auc(pr, Y), 3)}
    CAL.write_text(json.dumps(cal, indent=2) + "\n"); print("wrote", CAL)
