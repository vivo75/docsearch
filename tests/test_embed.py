from docsearch import embed


def test_suffix_is_appended_after_truncation_and_prefix_before(monkeypatch):
    seen = []
    e = embed.Embedder("http://x", suffix="<END>")
    monkeypatch.setattr(e, "_post", lambda texts: seen.extend(texts) or [[0.0, 1.0]] * len(texts))
    e.embed(["short", "y" * (embed.MAX_CHARS + 50)], "P:")
    assert sorted(seen, key=len) == ["P:short<END>", "P:" + "y" * embed.MAX_CHARS + "<END>"]
    assert e.truncated == 1


def test_production_model_constants():
    assert embed.MODEL_ID.startswith("Qwen3-Embedding") and embed.DOC_SUFFIX == embed.QWEN_EOS
    assert embed.qwen_query("q") == embed.QUERY_PREFIX + "q" + embed.QWEN_EOS


def test_server_errors_are_retried_before_text_is_cut(monkeypatch):
    import httpx
    monkeypatch.setattr(embed.time, "sleep", lambda s: None)
    e = embed.Embedder("http://x")
    calls = []

    def post(texts):
        calls.append(list(texts))
        if len(calls) < 3:
            r = httpx.Response(503, request=httpx.Request("POST", "http://x"))
            raise httpx.HTTPStatusError("busy", request=r.request, response=r)
        return [[0.0, 1.0]] * len(texts)
    monkeypatch.setattr(e, "_post", post)
    e.embed(["a" * 100])
    assert e.truncated == 0 and all(c == calls[0] for c in calls)      # same, untruncated text each time
