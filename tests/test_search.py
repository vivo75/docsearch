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
    assert {t.name for t in tools} == {"search_docs", "expand", "read_doc", "outline_doc", "browse", "grep_docs"}
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
    assert "PowerShell" in r["hits"][0]["snippet"] and r["hits"][0]["rerank_score"] == 5.0 and r["confidence"] == 5.0
    assert calls == [calls[0]] and "rerank_ms" in r["timings"]
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
