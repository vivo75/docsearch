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
