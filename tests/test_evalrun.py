import json

from docsearch.evalrun import load_questions, rank_of_first, score_question, summarize


def res(ranked, score=0.5, hits=()):
    return {"ranked": ranked, "hits": list(hits), "top_score": score, "tokens": 100, "latency_ms": 10.0}


def test_rank_and_metrics():
    q = {"id": "q", "category": "conceptual", "gold": ["a", "b"]}
    assert rank_of_first(["x", "b", "a"], {"a", "b"}) == 2
    s = score_question(q, res(["x", "b", "a"]))
    assert (s["r1"], s["r5"], s["mrr"], s["coverage10"]) == (False, True, 0.5, 1.0)
    assert 0 < s["ndcg10"] < 1
    miss = score_question(q, res(["x", "y"]))
    assert miss["rank"] is None and miss["mrr"] == 0.0 and miss["coverage10"] == 0.0


def test_variant_accuracy_and_unanswerable_auc():
    qv = {"id": "v", "category": "variant", "gold": ["a"], "expected_variant": "cli"}
    ok = score_question(qv, res(["a"], hits=[{"source": "a", "variants": ["portal,cli"]}]))
    bad = score_question(qv, res(["a"], hits=[{"source": "a", "variants": ["portal"]}]))
    assert ok["variant_ok"] and not bad["variant_ok"]
    rows = [score_question({"id": "1", "category": "conceptual", "gold": ["a"]}, res(["a"], 0.9)),
            score_question({"id": "2", "category": "unanswerable", "gold": []}, res(["z"], 0.1))]
    s = summarize(rows)
    assert s["unans_auc"] == 1.0 and s["R@5"] == 1.0 and s["n"] == 1


def test_question_file_is_consistent_and_lenient_only_adds():
    strict, lenient = load_questions(), load_questions(lenient=True)
    ids = [q["id"] for q in strict]
    assert len(ids) == len(set(ids)) and len(ids) >= 50
    assert {q["category"] for q in strict} >= {"conceptual", "identifier", "variant", "multi_page", "unanswerable"}
    for a, b in zip(strict, lenient):
        assert set(a["gold"]) <= set(b["gold"])
    assert all(q["gold"] == [] for q in strict if not q["answerable"])
    assert any(len(b["gold"]) > len(a["gold"]) for a, b in zip(strict, lenient))
