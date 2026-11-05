import sqlite3

from docsearch import conflicts


def mk():
    db = sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE docs(doc_id INTEGER, repo TEXT, path TEXT); CREATE TABLE chunks(doc_id INTEGER, text TEXT);"
                     "INSERT INTO docs VALUES (1,'r','a.md'),(2,'r','b.md');"
                     "INSERT INTO chunks VALUES (1,'node pool must be within two _minor_ versions of the control plane'),(2,'up to **three** minor versions ahead');")
    return db


C = {"id": "x", "pages": ["r/a.md", "r/b.md"], "note": "they differ",
     "evidence": [{"page": "r/a.md", "text": "within two minor versions"}, {"page": "r/b.md", "text": "up to three minor versions"}]}


def test_active_only_while_evidence_present():
    db = mk()
    assert conflicts.active(db, [C]) == [C]
    db.execute("UPDATE chunks SET text='fixed: three minor versions' WHERE doc_id=1")      # the page was corrected upstream
    assert conflicts.active(db, [C]) == []
    assert conflicts.active(db, [{**C, "note": ""}]) == [] and conflicts.active(db, [{**C, "evidence": []}]) == []


def test_notes_when_a_listed_page_is_returned():
    assert conflicts.notes([C], {"r/b.md"}) == ["conflicting sources (x): they differ"]
    assert conflicts.notes([C], {"r/zzz.md"}) == []
