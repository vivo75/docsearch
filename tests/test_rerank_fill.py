from types import SimpleNamespace

from docsearch.search import SearchConfig, Searcher


def row(doc, head):
    return {"doc_id": doc, "heading_path": head, "variant_tab": None, "variant_pivot": None, "variant_moniker": None}


def test_n_groups_matches_collapse_rules():
    s = Searcher.__new__(Searcher)
    s.cfg = SearchConfig(per_doc=2)
    hits = [SimpleNamespace(row=row(1, "a")), SimpleNamespace(row=row(1, "a")), SimpleNamespace(row=row(1, "b")),
            SimpleNamespace(row=row(1, "c")), SimpleNamespace(row=row(2, "a"))]
    assert s._n_groups(hits) == 3          # (1,a), (1,b), (2,a): same section merged, third section of doc 1 over the cap
