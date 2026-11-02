"""python eval/abstain.py [--rerankers bge-v2-m3-q8,qwen3-8b-q8,prism-4b-q8]
Abstention analysis on qset2 with cached rerank scores only (no reranker server): for each reranker, the server config is run over every
answerable + unanswerable question, the rerank scores of the top 10 chunks are recorded, and several "should we abstain?" signals are compared
by AUC (answerable vs unanswerable). Logistic combination and thresholds are fitted on dev and reported on test.
A reranker whose cache lacks dev questions (qwen/prism were run on test only) is analysed on test alone (leave-one-out thresholds are not used: AUC only)."""
import argparse, json, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
import compare
from compare import H, INDEXES, CONFIGS, load, auc
from docsearch import evalrun as E
from docsearch.config import load_config
from docsearch.expand import QueryExpander
from docsearch.calibration import PATH as CAL_PATH, fit, sigmoid
from docsearch.rerank import Reranker
from docsearch.server import _Embeddings

ap = argparse.ArgumentParser(); ap.add_argument("--rerankers", default="bge-v2-m3-q8,qwen3-8b-q8,qwen3-4b-q4,prism-4b-q8"); ap.add_argument("--index", default="nomic")
ap.add_argument("--calibrate", metavar="RERANKER", help="fit the confidence curve for this reranker on all scored qset2 questions and write src/docsearch/calibration.json")
a = ap.parse_args()
strict, _ = load("qset2", "all"); lab = {q["id"]: q for q in strict}
ex = QueryExpander("", H / "eval" / "qset2" / "expansions.json"); emb = _Embeddings(); cfg = load_config(H / "repos.toml")
memo = {t: emb(t) for q in strict for t in (q["question"], q["question"] + " " + ex.cache[q["question"]])}
db, _ = INDEXES[a.index]; config = CONFIGS["server"][0]


class CacheOnly(Reranker):
    def __init__(self, name):
        super().__init__("http://127.0.0.1:1", name, cache=H / "eval" / "qset2" / "rerank_cache.jsonl"); self.log = {}; self.miss = 0
    def score(self, q, docs):
        try: s = super().score(q, docs)
        except Exception: self.miss += 1; raise
        self.log[q] = sorted(s, reverse=True); return s


def features(s):
    s = np.array(s + [0.0] * (3 - len(s)))
    return {"max": s[0], "margin": s[0] - s[1], "top3mean": s[:3].mean(), "ratio": s[0] / (s[:5].sum() + 1e-9), "logit": np.log((s[0] + 1e-6) / (1 - s[0] + 1e-6))}


def run(name):
    rr = CacheOnly(name); sysm = E.DocsearchSystem(db, memo.__getitem__, cfg, config, name, measure=False, reranker=rr.score, expander=lambda q: ex.cache[q])
    rows = []
    for q in strict:
        try: sysm.run(q)
        except Exception: continue          # cache miss: question not scored with this reranker
        if q["question"] in rr.log:
            rows.append((q["id"], q["split"], not q.get("answerable", True) is False and q["category"] != "unanswerable", features(rr.log[q["question"]])))
    return rows


def roc_auc(pos, neg):
    return sum((p > n) + 0.5 * (p == n) for p in pos for n in neg) / (len(pos) * len(neg))


def logreg(X, y, l2=1.0, it=2000, lr=0.1):
    X = (X - X.mean(0)) / (X.std(0) + 1e-9); mu, sd = None, None
    w = np.zeros(X.shape[1] + 1); Xb = np.c_[X, np.ones(len(X))]
    for _ in range(it):
        p = 1 / (1 + np.exp(-Xb @ w)); w -= lr * (Xb.T @ (p - y) / len(y) + l2 * np.r_[w[:-1], 0] / len(y))
    return w


for name in ([] if a.calibrate else a.rerankers.split(",")):
    rows = run(name); n_by = {sp: sum(r[1] == sp for r in rows) for sp in ("dev", "test")}
    print(f"\n== {name}: scored {len(rows)} questions {n_by}, unanswerable {sum(not r[2] for r in rows)}")
    for sp in ("dev", "test"):
        R = [r for r in rows if r[1] == sp]
        if not any(not r[2] for r in R) or not any(r[2] for r in R): continue
        line = []
        for f in ("max", "margin", "top3mean", "ratio", "logit"):
            line.append(f"{f} {roc_auc([r[3][f] for r in R if r[2]], [r[3][f] for r in R if not r[2]]):.3f}")
        print(f"  AUC {sp:4s} ({sum(r[2] for r in R)} ans / {sum(not r[2] for r in R)} unans): " + "  ".join(line))
    dev = [r for r in rows if r[1] == "dev"]; test = [r for r in rows if r[1] == "test"]
    if dev and test:
        feats = ("max", "margin", "top3mean", "ratio")
        X = np.array([[r[3][f] for f in feats] for r in dev]); y = np.array([float(r[2]) for r in dev])
        w = logreg(X, y); m, s = X.mean(0), X.std(0) + 1e-9
        sc = lambda R: np.c_[(np.array([[r[3][f] for f in feats] for r in R]) - m) / s, np.ones(len(R))] @ w
        sd, st = sc(dev), sc(test); yd = np.array([r[2] for r in dev]); yt = np.array([r[2] for r in test])
        print(f"  logistic(max,margin,top3mean,ratio) AUC dev {roc_auc(sd[yd], sd[~yd]):.3f}  test {roc_auc(st[yt], st[~yt]):.3f}   (single 'max': test {roc_auc([r[3]['max'] for r in test if r[2]], [r[3]['max'] for r in test if not r[2]]):.3f})")
        for keep in (0.95, 0.90, 0.80):
            for label, fd, ft in (("max", np.array([r[3]["max"] for r in dev]), np.array([r[3]["max"] for r in test])), ("logistic", sd, st)):
                th = np.quantile(fd[yd], 1 - keep)            # abstain below th: keeps `keep` of dev answerable
                print(f"  keep {keep:.0%} answerable on dev [{label:8s}] -> test: answerable kept {(ft[yt] >= th).mean():.0%}, unanswerable correctly abstained {(ft[~yt] < th).mean():.0%}")


if a.calibrate:
    rows = run(a.calibrate)
    dev = [r for r in rows if r[1] == "dev"]; test = [r for r in rows if r[1] == "test"]
    if dev and test:       # held-out check: fit on dev, look at test (bins of the predicted probability against the observed answerable rate)
        ad, bd = fit([r[3]["max"] for r in dev], [r[2] for r in dev])
        p = np.array([sigmoid(ad * r[3]["max"] + bd) for r in test]); y = np.array([r[2] for r in test], float)
        print(f"\nheld-out calibration of the dev fit (a={ad:.3f}, b={bd:.3f}) on {len(test)} test questions, Brier {((p - y) ** 2).mean():.4f} (always-answerable: {((1 - y) ** 2).mean():.4f})")
        for lo, hi in ((0, .5), (.5, .8), (.8, .95), (.95, 1.01)):
            m = (p >= lo) & (p < hi)
            if m.any(): print(f"  predicted {lo:.2f}-{min(hi, 1):.2f}: n={int(m.sum()):3d}  mean predicted {p[m].mean():.2f}  observed answerable {y[m].mean():.2f}")
    a_, b_ = fit([r[3]["max"] for r in rows], [r[2] for r in rows])      # shipped fit: every scored question
    cal = json.loads(CAL_PATH.read_text()) if CAL_PATH.exists() else {}
    cal[a.calibrate] = {"a": round(a_, 5), "b": round(b_, 5), "n_answerable": sum(r[2] for r in rows), "n_unanswerable": sum(not r[2] for r in rows),
                        "fitted": time.strftime("%Y-%m-%d"), "set": "qset2 dev+test", "index": a.index}
    CAL_PATH.write_text(json.dumps(cal, indent=2) + "\n"); print("wrote", CAL_PATH, cal[a.calibrate])
