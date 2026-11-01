"""Two repos.toml entries sharing one checkout, both with `path` != `name` (the Azure CLI docs + reference layout).
Regression tests for the ultrareview findings 2-5 and 7."""
import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

from docsearch.build import build
from docsearch.config import load_config
from docsearch.grep import grep_docs
from docsearch.update import update

from test_azcli import YML
from test_update import FakeEmb, commit, sh

URL = "https://learn.microsoft.com/cli/azure"


def page(title, body):
    return f"---\ntitle: {title}\nms.topic: how-to\n---\n# {title}\n\n## Steps\n\n{body}\n"


@pytest.fixture()
def env(tmp_path):
    co = tmp_path / "corpus" / "cli-checkout"
    (co / "conceptual" / "includes").mkdir(parents=True); (co / "ref").mkdir()
    sh(co, "git", "init", "-q"); sh(co, "git", "config", "user.email", "a@b"); sh(co, "git", "config", "user.name", "n")
    (co / "conceptual/includes/note.md").write_text("Original shared note.")
    (co / "conceptual/install.md").write_text(page("Install", "Install uniqueinstallword. [!INCLUDE [n](includes/note.md)]"))
    (co / "conceptual/TOC.yml").write_text("items:\n- name: Install\n  href: install.md\n- name: az ts\n  href: ../ref/ts.yml\n")
    (co / "ref/ts.yml").write_text(YML)
    (co / "ref/TOC.yml").write_text("items:\n- name: az ts\n  href: ts.yml\n")
    (co / ".openpublishing.redirection.json").write_text(json.dumps({"redirections": [
        {"source_path": "conceptual/old-page.md", "redirect_url": "/cli/azure/install"},
        {"source_path": "ref/old-group.yml", "redirect_url": "/cli/azure/ts"}]}))
    commit(co, "init")
    cfg = tmp_path / "repos.toml"
    cfg.write_text(f'root = "corpus"\n'
                   f'[[repo]]\nname = "cli-docs"\npath = "cli-checkout"\ndocs_root = "conceptual"\nrestrict = true\nurl_base = "{URL}"\n'
                   f'[[repo]]\nname = "cli-ref"\npath = "cli-checkout"\ndocs_root = "ref"\nrestrict = true\nformat = "azcli-yaml"\n'
                   f'url_base = "{URL}"\n')
    out = tmp_path / "data"
    build(str(cfg), out, embedder=FakeEmb(), workers=1)
    return {"co": co, "cfg": cfg, "out": out}


def db(env):
    return sqlite3.connect(f"file:{env['out'] / 'current.db'}?mode=ro", uri=True)


def test_include_change_reprocesses_dependent_page(env):          # finding 2
    (env["co"] / "conceptual/includes/note.md").write_text("Updated shared note newnoteword.")
    commit(env["co"], "edit include")
    update(str(env["cfg"]), env["out"], embedder=FakeEmb(), workers=1)
    text = " ".join(t for (t,) in db(env).execute(
        "SELECT c.text FROM chunks c JOIN docs d USING(doc_id) WHERE d.repo='cli-docs' AND d.path='conceptual/install.md'"))
    assert "newnoteword" in text


def test_redirects_of_both_entries_survive_incremental_update(env):   # finding 3
    before = dict(db(env).execute("SELECT old_url, new_url FROM redirects"))
    assert f"{URL}/old-page" in before and f"{URL}/old-group" in before
    (env["co"] / "ref/ts.yml").write_text(YML.replace("Manage template specs.", "Manage template specs, edited."))
    commit(env["co"], "edit reference")
    update(str(env["cfg"]), env["out"], embedder=FakeEmb(), workers=1)
    after = dict(db(env).execute("SELECT old_url, new_url FROM redirects"))
    assert after == before


def test_grep_hits_are_index_sources_once(env):                   # findings 4 + 5
    from docsearch.search import SearchConfig, Searcher
    cfg = load_config(env["cfg"])
    res = grep_docs(cfg, "uniqueinstallword")
    assert [m["source"] for m in res["matches"]] == ["cli-docs/conceptual/install.md"]     # mapped, not duplicated
    assert res["files_matched"] == 1
    s = Searcher(env["out"] / "current.db", lambda q: b"", {r.name: r.weight for r in cfg.repos}, SearchConfig())
    assert "error" not in s.read_doc(res["matches"][0]["source"])


def test_toc_scoped_to_entry_and_resolved_across_siblings(env):    # finding 7
    rows = db(env).execute("SELECT repo, toc_path, href, doc_id FROM toc ORDER BY node_id").fetchall()
    assert {(r, p) for r, p, _, _ in rows} == {("cli-docs", "conceptual/TOC.yml"), ("cli-ref", "ref/TOC.yml")}
    assert all(d is not None for _, _, _, d in rows)              # incl. the conceptual link into the reference
