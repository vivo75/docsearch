"""The lazy backends of the MCP server must recover after a crash instead of staying 'lexical only' until a restart."""
from docsearch import server


class FakeSrv:
    url = "http://x"
    stopped = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        FakeSrv.stopped += 1


class FlakyEmb:
    alive = {"ok": False}

    def __init__(self, url):
        pass

    def embed(self, texts, prefix=""):
        if not FlakyEmb.alive["ok"]:
            raise ConnectionError("llama-server gone")
        return [b"v"] * len(texts)


def test_embeddings_restart_after_backend_death(monkeypatch):
    monkeypatch.setattr(server, "prod_server", lambda **k: FakeSrv())
    monkeypatch.setattr(server, "prod_embedder", FlakyEmb)
    e = server._Embeddings()
    try:
        e("q")
    except ConnectionError:
        pass
    assert e.emb is None and FakeSrv.stopped == 1          # dropped, server stopped
    e.failed_at = 0                                         # the 60 s back-off has passed
    FlakyEmb.alive["ok"] = True
    assert e("q") == b"v"                                   # a fresh server was started


def test_reranking_restart_after_backend_death(monkeypatch):
    class R:
        ok = False

        def __init__(self, url, name):
            pass

        def score(self, q, docs):
            if not R.ok:
                raise ConnectionError("gone")
            return [1.0] * len(docs)
    monkeypatch.setattr(server, "RerankServer", lambda *a, **k: FakeSrv())
    monkeypatch.setattr(server, "Reranker", R)
    r = server._Reranking("bge-v2-m3-q8")
    try:
        r("q", ["d"])
    except ConnectionError:
        pass
    assert r.rr is None
    r.failed_at = 0; R.ok = True
    assert r("q", ["d"]) == [1.0]
