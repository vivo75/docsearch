from docsearch.search import stale_warnings


def h(title, src, date, svc="aks", topic="how-to"):
    return {"title": title, "source": src, "meta": {"ms_date": date, "service": svc, "topic": topic}}


def test_old_top_hit_vs_newer_same_service():
    r = [h("Node pools", "a.md", "2023-10-05"), h("Control plane", "b.md", "2026-08-03"), h("Other", "c.md", "2026-09-01", svc="x")]
    w = stale_warnings(r)
    assert len(w) == 1 and "hit 1" in w[0] and "2023-10-05" in w[0] and "2y10m" in w[0]


def test_no_warning_cases():
    assert stale_warnings([h("A", "a.md", "2023-10-05"), h("B", "b.md", "2025-06-01")]) == []             # gap 20 months
    assert stale_warnings([h("A", "a.md", "2023-10-05"), h("B", "b.md", "2026-08-03", svc="x")]) == []    # other service
    assert stale_warnings([h("A", "a.md", None), h("B", "b.md", "2026-08-03")]) == []                    # unknown date
    assert stale_warnings([h("A", "a.md", "2024-01-01", topic="release-notes"), h("B", "b.md", "2026-08-03")]) == []
    assert stale_warnings([h("N", "n.md", "2026-08-03"), h("O", "o.md", "2020-01-01")], top=1) == []        # old page not in the first `top`
