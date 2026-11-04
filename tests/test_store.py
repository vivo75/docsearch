from docsearch import store


def test_ident_tokens():
    t = store.ident_tokens("Run `az vm create --resource-group rg` on Microsoft.Storage/storageAccounts. plain words")
    assert "--resource-group" not in t and "resource-group" in t
    assert "microsoft.storage/storageaccounts" in t and "plain" not in t


def test_schema_and_health(tmp_path):
    db = store.create(tmp_path / "i.db")
    db.execute("INSERT INTO docs(repo,path,title) VALUES ('r','p.md','T')")
    db.execute("INSERT INTO chunks(rid,chunk_id,doc_id,text,content_hash) VALUES (1,'c1',1,'hello','h')")
    assert any("vec rows" in p for p in store.health(db))
    db.execute("INSERT INTO chunks_vec(rowid, embedding) VALUES (1, ?)", [bytes(4 * store.DIMS)])
    db.execute("INSERT INTO chunks_fts(rowid,title,description,heading_path,text) VALUES (1,'T','','','hello')")
    db.execute("INSERT INTO chunks_ident(rowid,tokens) VALUES (1,'')")
    assert store.health(db) == []


def test_swap_prunes_and_repoints(tmp_path):
    for i in range(5):
        (tmp_path / f"index-{i}.db").write_text(str(i))
    link = tmp_path / "current.db"
    store.swap(tmp_path / "index-4.db", link, keep=2)
    assert link.read_text() == "4" and len(list(tmp_path.glob("index-*.db"))) == 2
    store.swap(tmp_path / "index-3.db", link, keep=2)
    assert link.read_text() == "3"


def test_swap_never_prunes_the_live_index_and_drops_stale_partials(tmp_path):
    import os, time
    for i in range(4):
        p = tmp_path / f"index-{i}.db"
        p.write_text(str(i))
        os.utime(p, (1000 + i, 1000 + i))
    live = tmp_path / "index-0.db"                        # the OLDEST file is the live one (e.g. a rollback)
    os.utime(live, (1, 1))
    link = tmp_path / "current.db"
    link.symlink_to(live.name)
    (tmp_path / "index-0.db.vec.npy").write_text("v")
    old, fresh = tmp_path / "index-9.partial", tmp_path / "index-10.partial"
    old.write_text("x"); fresh.write_text("y")
    os.utime(old, (time.time() - 10 * 86400,) * 2)
    store.swap(live, link, keep=2)
    assert link.read_text() == "0" and (tmp_path / "index-0.db.vec.npy").exists()
    assert len(list(tmp_path.glob("index-*.db"))) == 2     # live + one newest other
    assert not old.exists() and fresh.exists()
