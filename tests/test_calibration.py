import json

from docsearch.calibration import calibrator, fit, sigmoid


def test_fit_separates_and_is_monotone():
    scores = [-3, -2, -1.5, -1, 0.5, 1, 2, 3, 4, 5, 6, -0.5, 0.0, 1.5]
    answerable = [False, False, False, False, True, True, True, True, True, True, True, False, True, True]
    a, b = fit(scores, answerable)
    assert a > 0
    ps = [sigmoid(a * s + b) for s in sorted(scores)]
    assert ps == sorted(ps) and ps[0] < 0.2 and ps[-1] > 0.9
    assert abs(sigmoid(1000) - 1) < 1e-12 and sigmoid(-1000) < 1e-12        # no overflow


def test_calibrator_reads_per_reranker_and_degrades_to_none(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"m1": {"a": 1.0, "b": 0.0}}))
    assert calibrator("m1", f)(0.0) == 0.5 and calibrator("m1", f)(10) > 0.99
    assert calibrator("other", f) is None and calibrator("m1", tmp_path / "missing.json") is None
    f.write_text("{not json")
    assert calibrator("m1", f) is None
