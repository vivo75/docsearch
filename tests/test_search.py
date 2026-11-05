import asyncio
import hashlib
import re
from array import array

import pytest

from docsearch import store
from docsearch.config import Config, Repo
from docsearch.grep import grep_docs
from docsearch.search import Filters, Searcher, parse_query
from docsearch.store import ident_tokens


def fake_embed(text: str) -> bytes:
    """Hashing-trick bag of words: texts sharing words are close in cosine space."""
    v = [0.0] * store.DIMS
    for w in re.findall(r"[a-z0-9]+", text.lower().replace("search_query:", "")):
        v[int(hashlib.md5(w.encode()).hexdigest(), 16) % store.DIMS] += 1.0
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return array("f", [x / n for x in v]).tobytes()


@pytest.fixture()
def idx(tmp_path):
    db = store.create(tmp_path / "i.db")
    docs = [
        (1, "azure-docs", "articles/storage/create.md", "https://learn.microsoft.com/azure/storage/create",
         "Create a storage account", "azure-storage", "how-to", "2026-03-01"),
        (2, "azure-docs", "articles/net/overview.md", "https://learn.microsoft.com/azure/net/overview",
         "Networking overview", "azure-vnet", "overview", "2020-01-01"),
        (3, "azure-rest-api-specs", "specs/readme.md", None, "Storage spec", None, None, None),
    ]
    for d in docs:
        db.execute("INSERT INTO docs(doc_id,repo,path,url,title,ms_service,ms_topic,ms_date,description) VALUES (?,?,?,?,?,?,?,?,'')", d)
    chunks = [  # rid, id, doc, heading, anchor, tab, pivot, text, prev, next, parent
        (1, "c1", 1, "", "", None, None, "Choose a tool to create the storage account.", None, "c2", "c1"),
        (2, "c2", 1, "Create", "create", None, "azure-cli", "Run az storage account create --resource-group rg1 --name acct.", "c1", "c4", "c2"),
        (3, "c3", 1, "Create", "create", None, "azure-powershell", "Run New-AzStorageAccount -ResourceGroupName rg1 to create the account.", None, "c5", "c3"),
        (4, "c4", 1, "Next steps", "next-steps", None, "azure-cli", "Rotate account keys with the CLI afterwards.", "c2", None, "c2"),
        (5, "c5", 1, "Next steps", "next-steps", None, "azure-powershell", "Rotate account keys with PowerShell afterwards.", "c3", None, "c3"),
        (6, "c6", 2, "Firewalls", "firewalls", None, None, "Restrict network access with virtual network rules and firewall settings.", None, None, "c6"),
        (7, "c7", 3, "Ops", "ops", None, None, "Microsoft.Storage/storageAccounts operations spec for create.", None, None, "c7"),
    ]
    for rid, cid, doc, hp, anc, tab, piv, text, prev, nxt, par in chunks:
        db.execute("INSERT INTO chunks(rid,chunk_id,doc_id,heading_path,anchor,variant_tab,variant_pivot,text,prev_id,next_id,parent_id,token_count,content_hash)"
                   " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'h')", (rid, cid, doc, hp, anc, tab, piv, text, prev, nxt, par, 12))
        title = {1: "Create a storage account", 2: "Networking overview", 3: "Storage spec"}[doc]
        db.execute("INSERT INTO chunks_fts(rowid,title,description,heading_path,text) VALUES (?,?,?,?,?)", (rid, title, "", hp, text))
        db.execute("INSERT INTO chunks_ident(rowid,tokens) VALUES (?,?)", (rid, ident_tokens(title, hp, text)))
        db.execute("INSERT INTO chunks_vec(rowid,embedding) VALUES (?,?)", (rid, fake_embed(title + " " + hp + " " + text)))
    db.execute("INSERT INTO redirects VALUES ('https://learn.microsoft.com/azure/storage/old','https://learn.microsoft.com/azure/storage/create')")
    db.execute("INSERT INTO toc(node_id,parent_id,ord,repo,toc_path,name,href,doc_id,url) VALUES (1,NULL,0,'azure-docs','articles/storage/TOC.yml','Storage','x.md',1,'https://learn.microsoft.com/azure/storage/create')")
    db.execute("INSERT INTO toc(node_id,parent_id,ord,repo,toc_path,name,href,doc_id,url) VALUES (2,1,0,'azure-docs','articles/storage/TOC.yml','Child',NULL,NULL,NULL)")
    for nid, par, o, doc, name, url in ((10, None, 0, None, "Networking section", None), (11, 10, 0, 2, "Networking overview", "https://learn.microsoft.com/azure/storage/net"),
                                        (12, 10, 1, None, "A folder", None), (13, 10, 2, 3, "Storage spec", "https://learn.microsoft.com/azure/storage/spec")):
        db.execute("INSERT INTO toc(node_id,parent_id,ord,repo,toc_path,name,href,doc_id,url) VALUES (?,?,?,'azure-docs','articles/zz/TOC.yml',?,NULL,?,?)", (nid, par, o, name, doc, url))
    db.commit(); db.close()
    return tmp_path / "i.db"


def S(idx, semantic=True):
    return Searcher(idx, fake_embed if semantic else None, {"azure-rest-api-specs": 0.3})


def test_parse_query():
    pq = parse_query('how do I run "az group create" with --resource-group in Microsoft.Storage/accounts')
    assert "group create" in " ".join(pq.phrases) or "az group create" in pq.phrases
    assert "resource-group" in pq.idents and "microsoft.storage/accounts" in pq.idents
    assert "how" not in pq.terms and "resource-group" in pq.terms


def test_hybrid_and_lexical_only(idx):
    r = S(idx).search("restrict network access firewall")
    assert r["hits"][0]["source"].endswith("net/overview.md") and not r["warnings"]
    r = S(idx, semantic=False).search("restrict network access firewall")
    assert r["hits"][0]["source"].endswith("net/overview.md") and "lexical only" in r["warnings"][0]


def test_identifier_and_weights(idx):
    r = S(idx).search("--resource-group")
    assert r["hits"][0]["chunk_id"] == "c2"
    r = S(idx).search("Microsoft.Storage/storageAccounts", Filters(repo="azure-rest-api-specs"))   # opt-in
    assert r["hits"][0]["source"].startswith("azure-rest-api-specs/")
    unfiltered = S(idx).search("Microsoft.Storage/storageAccounts operations spec", limit=10)["hits"]
    specs = [i for i, h in enumerate(unfiltered) if h["source"].startswith("azure-rest-api-specs/")]
    assert specs and specs[0] > 0                                                             # demoted by repo weight


def test_pivot_filter_keeps_shared_and_drops_other_variant(idx):
    ids = {h["chunk_id"] for h in S(idx).search("create storage account", Filters(pivot="azure-cli"), limit=10)["hits"]}
    assert "c1" in ids and "c2" in ids and "c3" not in ids and "c5" not in ids


def test_variants_grouped_into_one_hit(idx):
    hits = S(idx).search("rotate account keys", limit=10)["hits"]
    nxt = [h for h in hits if h["heading"] == "Next steps"]
    assert len(nxt) == 1 and sorted(nxt[0]["variants"]) == ["azure-cli", "azure-powershell"]


def test_filters_service_topic_date(idx):
    s = S(idx)
    assert {h["source"].split("/")[0] for h in s.search("network storage", Filters(repo="azure-docs"))["hits"]} == {"azure-docs"}
    assert all(h["meta"]["service"] == "azure-storage" for h in s.search("account", Filters(service="azure-storage"))["hits"])
    assert all(h["meta"]["ms_date"] >= "2025-01-01" for h in s.search("account network", Filters(date_after="2025-01-01"))["hits"])


def test_malformed_query_does_not_raise(idx):
    for q in ['"', "AND OR", "(((", "*", "a:b", '"unterminated phrase']:
        assert "hits" in S(idx).search(q)


def test_token_budget_and_untrusted_note(idx):
    r = S(idx).search("account", limit=8, max_tokens=500)
    assert "untrusted" in r["note"] and r["hits"]


def test_expand_chunk_and_section(idx):
    s = S(idx)
    assert [c["chunk_id"] for c in s.expand("c2", 1)["chunks"]] == ["c1", "c2", "c4"]
    assert [c["chunk_id"] for c in s.expand("c4", scope="section")["chunks"]] == ["c2", "c4"]
    assert "error" in s.expand("nope")


def test_read_doc_lookup_redirect_variant_section_paging(idx):
    s = S(idx)
    for ref in ("https://learn.microsoft.com/azure/storage/create", "/azure/storage/old/", "azure-docs/articles/storage/create.md",
                "articles/storage/create.md"):
        assert s.read_doc(ref)["title"] == "Create a storage account"
    r = s.read_doc("articles/storage/create.md", variant="azure-cli")
    assert "az storage account create" in r["text"] and "New-AzStorageAccount" not in r["text"]
    assert "Rotate account keys with the CLI" in s.read_doc("articles/storage/create.md", section="next steps", variant="azure-cli")["text"]
    r = s.read_doc("articles/storage/create.md", max_tokens=1)
    assert r["chunks_returned"] == 1 and r["next_offset"] == 1
    assert r["truncated"] is True and "PARTIAL" in r["note"] and "offset=1" in r["note"] and r["omitted_headings_total"] == len(r["omitted_headings"])
    full = s.read_doc("articles/storage/create.md", max_tokens=20000)
    assert full["next_offset"] is None and "truncated" not in full and "note" not in full
    assert "error" in s.read_doc("https://learn.microsoft.com/azure/nothing")


def test_outline_and_browse(idx):
    s = S(idx)
    o = s.outline_doc("articles/storage/create.md")["outline"]
    assert [n["heading"] for n in o] == ["Create", "Next steps"] and o[0]["variants"] == ["azure-cli", "azure-powershell"]
    assert s.browse(repo="azure-docs")["tocs"][0]["toc_path"] == "azure-docs/articles/storage/TOC.yml"
    top = s.browse(toc_path="azure-docs/articles/storage/TOC.yml")["children"]
    assert top[0]["name"] == "Storage" and top[0]["children"] == 1
    assert s.browse(node_id=1)["children"][0]["name"] == "Child"


def test_grep_confined_and_works(tmp_path):
    (tmp_path / "r1").mkdir(); (tmp_path / "secret").mkdir()
    (tmp_path / "r1" / "a.md").write_text("alpha\nFooBar_Baz error\nomega\n")
    (tmp_path / "secret" / "s.md").write_text("FooBar_Baz outside\n")
    cfg = Config(tmp_path, (Repo("r1", tmp_path / "r1", "."),))
    r = grep_docs(cfg, "foobar_baz")
    assert [m["source"] for m in r["matches"]] == ["r1/a.md"] and any(l["match"] for l in r["matches"][0]["lines"])
    assert "error" in grep_docs(cfg, "x", glob="../secret/*.md")
    assert "error" in grep_docs(cfg, "x", glob="/etc/*")
    assert "error" in grep_docs(cfg, "")
    assert "error" in grep_docs(cfg, "(", regex=True)


def test_mcp_tools_registered_and_callable(idx, tmp_path):
    from docsearch.server import make_server
    srv = make_server(idx)
    tools = asyncio.run(srv.list_tools())
    assert {t.name for t in tools} == {"search_docs", "expand", "read_doc", "outline_doc", "browse", "grep_docs", "azurerm_object"}
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)


def test_searcher_usable_from_another_thread(idx):
    import concurrent.futures as cf
    s = S(idx)
    with cf.ThreadPoolExecutor(4) as ex:
        res = list(ex.map(lambda q: s.search(q)["hits"], ["storage account", "network firewall", "rotate keys", "az storage"] * 3))
    assert all(res)


def test_rerank_replace_rrf_and_failure_fallback(idx):
    calls = []

    def fake(query, docs):                 # "likes" documents mentioning PowerShell
        calls.append(len(docs))
        return [5.0 if "PowerShell" in d else -1.0 for d in docs]

    from docsearch.search import SearchConfig
    base = S(idx).search("create storage account", limit=5)["hits"]
    assert "powershell" not in base[0]["snippet"].lower()
    r = Searcher(idx, fake_embed, {"azure-rest-api-specs": 0.3}, SearchConfig(rerank_top=10), fake).search("create storage account", limit=5)
    assert "PowerShell" in r["hits"][0]["snippet"] and r["hits"][0]["rerank_score"] == 5.0 and r["rerank_max"] == 5.0
    assert "confidence" not in r                                       # no calibration given: the raw score only
    assert calls == [calls[0]] and "rerank_ms" in r["timings"]
    rc = Searcher(idx, fake_embed, {"azure-rest-api-specs": 0.3}, SearchConfig(rerank_top=10), fake, calibrate=lambda x: 0.25).search("create storage account", limit=5)
    assert rc["confidence"] == 0.25 and rc["rerank_max"] == 5.0
    r2 = Searcher(idx, fake_embed, {"azure-rest-api-specs": 0.3}, SearchConfig(rerank_top=10, rerank_mode="rrf", rerank_weight=0.2), fake).search("create storage account", limit=5)
    assert r2["hits"][0]["chunk_id"] == base[0]["chunk_id"]            # weak reranker weight keeps the fused leader

    def boom(q, d):
        raise RuntimeError("down")
    r3 = Searcher(idx, fake_embed, {"azure-rest-api-specs": 0.3}, SearchConfig(rerank_top=10), boom).search("create storage account", limit=5)
    assert [h["chunk_id"] for h in r3["hits"]] == [h["chunk_id"] for h in base] and "reranker unavailable" in r3["warnings"][0]


def test_searcher_follows_symlink_swap(idx, tmp_path):
    import shutil
    link = tmp_path / "current.db"
    link.symlink_to(idx.name) if (tmp_path / idx.name).exists() else link.symlink_to(idx)
    s = Searcher(link, fake_embed, {})
    assert s.read_doc("articles/storage/create.md")["title"] == "Create a storage account"
    new = tmp_path / "second.db"
    shutil.copyfile(idx, new)
    db = store.connect(new)
    db.execute("UPDATE docs SET title='Renamed page' WHERE doc_id=1"); db.commit(); db.close()
    tmp = tmp_path / "current.db.tmp"; tmp.symlink_to(new); tmp.replace(link)
    assert s.read_doc("articles/storage/create.md")["title"] == "Renamed page"


def test_selective_filter_falls_back_to_exact_ranking(idx):
    s = S(idx, semantic=False)
    # only c7 (spec repo) matches this filter; the oversampled head can't fill `limit`, so the exact path must find it
    r = s.search("storage account operations", Filters(repo="azure-rest-api-specs"), limit=5)["hits"]
    assert [h["chunk_id"] for h in r] == ["c7"]
    assert s._lexical("chunks_fts", '"storage"', Filters(), "10, 5, 3, 1", 3)      # unfiltered fast path


def test_query_expansion_bridges_vocabulary_gap_and_degrades_gracefully(idx):
    from docsearch.search import SearchConfig
    calls = []

    def expander(q):
        calls.append(q)
        return "NewAzStorageAccount PowerShell cmdlet"       # the documentation's own words

    plain = Searcher(idx, fake_embed, {}, SearchConfig()).search("make an account", limit=8)["hits"]
    cfgx = SearchConfig(expand_lex=1.0, expand_vec=1.0)
    r = Searcher(idx, fake_embed, {}, cfgx, None, expander).search("make an account", limit=8)
    assert calls == ["make an account"] and "expand_ms" in r["timings"]
    rank = lambda hits, cid: next((i for i, h in enumerate(hits) if h["chunk_id"] == cid), 99)
    assert rank(r["hits"], "c3") <= rank(plain, "c3")                      # expansion mentions PowerShell -> c3 not worse

    def boom(q):
        raise RuntimeError("down")
    r2 = Searcher(idx, fake_embed, {}, cfgx, None, boom).search("make an account", limit=8)
    assert [h["chunk_id"] for h in r2["hits"]] == [h["chunk_id"] for h in plain] and "expansion unavailable" in r2["warnings"][0]


def test_hits_carry_their_place_in_the_toc(idx):
    s = S(idx)
    hit = lambda q: s.search(q, limit=3)["hits"][0]
    net = hit("virtual network rules firewall")
    assert net["source"].endswith("networking.md") or net["title"] == "Networking overview"
    t = net["toc"]
    assert t["path"] == "Networking section" and t["node_id"] == 11
    assert "prev" not in t and t["next"] == {"name": "Storage spec", "url": "https://learn.microsoft.com/azure/storage/spec"}   # the folder (no url) is skipped
    root = hit("create storage account")
    assert root["title"] == "Create a storage account" and root["toc"] == {"node_id": 1}              # a root entry: no ancestors, no siblings
    assert s.read_doc("articles/net/overview.md")["toc"]["path"] == "Networking section"
    assert s.outline_doc("articles/net/overview.md")["toc"]["node_id"] == 11


def test_page_outside_any_toc_has_no_toc_field(idx):
    s = S(idx)
    assert s._toc_context(999) is None and s._toc_field(999) == {}


def test_shingles_ignore_link_targets_and_short_texts():
    from docsearch.search import near_duplicate, shingles
    a = shingles("Run [terraform apply](https://www.terraform.io/docs/commands/apply.html) to apply the execution plan to your cloud infrastructure.")
    b = shingles("Run [terraform apply](https://developer.hashicorp.com/terraform/cli/commands/apply) to apply the execution plan to your cloud infrastructure.")
    c = shingles("Run terraform plan to create an execution plan for your cloud infrastructure and save it for later use.")
    assert near_duplicate(a, b, 0.9) and not near_duplicate(a, c, 0.5)
    assert shingles("Next steps") is None and not near_duplicate(None, a, 0.1)


def test_dedup_keeps_best_hit_and_lists_the_copies(idx):
    from docsearch.search import Hit, SearchConfig
    boiler = "Run terraform apply to apply the execution plan to your cloud infrastructure. The example command assumes you previously ran terraform plan."
    mk = lambda rid, doc, text: Hit(rid, 1.0 / rid, {"doc_id": doc, "text": text, "title": f"t{doc}", "heading_path": "h", "url": f"u{doc}", "repo": "r", "path": f"p{doc}",
                                              "chunk_id": f"c{rid}", "anchor": "", "ms_service": None, "ms_topic": None, "ms_date": None, "last_commit_date": None})
    hits = [mk(1, 1, boiler), mk(2, 2, boiler + " "), mk(3, 3, "Something else entirely about virtual network peering and gateway transit settings in hub spoke."),
            mk(4, 1, boiler), mk(5, 4, "Short")]
    s = Searcher(idx, fake_embed, {}, SearchConfig(dedup=0.8))
    out = s._dedup(hits)
    assert [h.rid for h in out] == [1, 3, 5]                                   # rid 2 merged into 1; rid 4 is the same page: dropped silently
    assert [a.rid for a in out[0].also] == [2] and out[1].also == []
    rendered = s._render(out, 1000)
    assert rendered[0]["also_in_total"] == 1 and rendered[0]["also_in"][0]["url"] == "u2" and "also_in" not in rendered[1]



def test_vecmat_matches_sqlite_vec_and_falls_back(idx, monkeypatch):
    from docsearch import vecmat
    s0 = S(idx)
    assert s0.vecmat is None                                       # no cache yet -> sqlite-vec
    assert vecmat.build(idx) == 7
    s1 = S(idx)
    assert s1.vecmat is not None
    for q in ("create storage account", "firewall network rules", "rotate keys powershell"):
        for f in (Filters(), Filters(service="azure-storage"), Filters(pivot="azure-cli")):
            assert set(s1._vector(q, f, 10)) == set(s0._vector(q, f, 10)), (q, f)       # same candidates under every filter
    assert s1._vector("create storage account", Filters(), 2) == s0._vector("create storage account", Filters(), 2)   # same order (no ties at the top)
    assert s1.search("create storage account")["hits"]             # full pipeline on the matrix path
    monkeypatch.setenv("DOCSEARCH_VECMAT", "off")
    assert S(idx).vecmat is None
    monkeypatch.delenv("DOCSEARCH_VECMAT")
    vecmat.paths(idx)[0].write_bytes(b"junk")                       # corrupt cache: ignored, not fatal
    assert S(idx).vecmat is None


def test_vecmat_rejects_wrong_dimension(idx):
    from docsearch import vecmat
    vecmat.build(idx)
    with pytest.raises(ValueError):
        S(idx).vecmat.top(bytes(4 * 768), 3)


def test_models_run_outside_the_searcher_lock(idx):
    """A slow embedder (cold model start) must not block read_doc/browse in other threads."""
    import threading
    started, release = threading.Event(), threading.Event()

    def slow_embed(text):
        started.set()
        assert release.wait(10)
        return fake_embed(text)
    s = Searcher(idx, slow_embed, {})
    out = {}
    t = threading.Thread(target=lambda: out.update(r=s.search("storage account")))
    t.start()
    assert started.wait(10)
    done = threading.Event()
    threading.Thread(target=lambda: (s.read_doc("articles/storage/create.md"), done.set())).start()
    assert done.wait(5), "read_doc was blocked by a search waiting for the embedder"
    release.set(); t.join(10)
    assert out["r"]["hits"]


def test_failed_reopen_keeps_serving_the_old_index(idx, tmp_path):
    link = tmp_path / "current.db"
    link.symlink_to(idx)
    s = Searcher(link, fake_embed, {})
    bad = tmp_path / "broken.db"
    bad.write_text("not a database")
    tmp = tmp_path / "current.db.tmp"; tmp.symlink_to(bad); tmp.replace(link)
    assert s.search("storage account")["hits"]                         # old index still answers
    assert s.read_doc("articles/storage/create.md")["title"] == "Create a storage account"


def test_read_doc_variant_uses_tolerant_matching(idx):
    r = S(idx).read_doc("articles/storage/create.md", variant="cli")    # tab ids are "azure-cli" in the data
    assert "az storage account create" in r["text"] and "New-AzStorageAccount" not in r["text"]


def test_filtered_lexical_is_ranked_by_bm25(idx):
    s = S(idx, semantic=False)
    f = Filters(service="azure-storage")
    ranked = s._lexical("chunks_fts", '"account" OR "rotate"', f, "10, 5, 3, 1", 10)
    alone = s._lexical("chunks_fts", '"account" OR "rotate"', Filters(), "10, 5, 3, 1", 10)
    assert ranked == [r for r in alone if r in ranked]                  # same relative order as the unfiltered BM25 ranking


def test_extra_queries_widen_recall_and_rerank_takes_the_best_score(idx):
    from docsearch.search import SearchConfig
    s = S(idx, semantic=False)
    plain = [h["chunk_id"] for h in s.search("firewall", limit=8)["hits"]]
    assert "c7" not in plain                                            # the spec chunk has nothing to do with "firewall"
    more = s.search("firewall", limit=8, extra_queries=["Microsoft.Storage/storageAccounts operations", "firewall", "  "])
    ids = [h["chunk_id"] for h in more["hits"]]
    assert "c7" in ids and "c6" in ids                                    # main-query hits are kept; the extra one is added
    seen = []

    def rr(q, docs):
        seen.append(q)
        return [3.0 if "storageAccounts" in d and "operations" in q else 0.0 for d in docs]
    r = Searcher(idx, None, {}, SearchConfig(rerank_top=10, rerank_mode="replace"), rr).search(
        "firewall", limit=8, extra_queries=["Microsoft.Storage/storageAccounts operations"])
    assert seen == ["firewall", "Microsoft.Storage/storageAccounts operations"]      # duplicates and blanks are dropped
    assert r["hits"][0]["chunk_id"] == "c7" and r["rerank_max"] == 3.0


def test_relevance_is_calibrated_per_hit_and_falls_with_position(idx):
    from docsearch.search import SearchConfig
    rr = lambda q, docs: [2.0 for _ in docs]
    s = Searcher(idx, None, {}, SearchConfig(rerank_top=10, rerank_mode="replace"), rr,
                 calibrate_hit=lambda score, pos: 1 / (1 + 2.718281828 ** -(score - pos)))
    hits = s.search("firewall", limit=8)["hits"]
    rel = [h["relevance"] for h in hits if "relevance" in h]
    assert rel and rel == sorted(rel, reverse=True) and rel[0] > rel[-1] or len(rel) == 1
    assert "relevance" not in Searcher(idx, None, {}, SearchConfig(rerank_top=10, rerank_mode="replace"), rr).search("firewall")["hits"][0]
