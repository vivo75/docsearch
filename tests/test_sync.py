import subprocess

from docsearch.config import Repo
from docsearch.sync import DepGraph, diff, head, is_page, list_pages


def sh(cwd, *a):
    subprocess.run(a, cwd=cwd, check=True, capture_output=True)


def test_is_page():
    assert is_page("articles/a.md") and not is_page("articles/includes/a.md") and not is_page("a.txt")


def test_diff_and_affected(tmp_path):
    sh(tmp_path, "git", "init", "-q")
    sh(tmp_path, "git", "config", "user.email", "a@b"); sh(tmp_path, "git", "config", "user.name", "n")
    (tmp_path / "includes").mkdir(); (tmp_path / "a").mkdir()
    (tmp_path / "includes/i.md").write_text("one")
    (tmp_path / "a/p.md").write_text("page content long enough to stay similar " * 5)
    (tmp_path / "a/q.md").write_text("other")
    (tmp_path / "a/old.md").write_text("to be deleted")
    sh(tmp_path, "git", "add", "."); sh(tmp_path, "git", "commit", "-qm", "1")
    repo = Repo("t", tmp_path, ".")
    old = head(repo)
    assert list_pages(repo) == ["a/old.md", "a/p.md", "a/q.md"]
    (tmp_path / "includes/i.md").write_text("two")
    sh(tmp_path, "git", "mv", "a/p.md", "a/p2.md")
    sh(tmp_path, "git", "rm", "-q", "a/old.md")
    sh(tmp_path, "git", "add", "."); sh(tmp_path, "git", "commit", "-qm", "2")
    cs = diff(repo, old, head(repo))
    assert cs.renamed == {"a/p.md": "a/p2.md"} and cs.deleted == {"a/old.md"} and "includes/i.md" in cs.modified
    g = DepGraph(); g.set_deps("t/a/q.md", {"t/includes/i.md"})
    assert g.affected_pages(cs, "t/") == {"a/p2.md", "a/q.md"}


def test_repo_restrict_limits_pages_to_docs_root(tmp_path):
    from docsearch.config import Repo
    r = Repo("x", tmp_path, "azps-2", restrict=True)
    assert r.in_scope("azps-2/Az.A/Get-A.md") and not r.in_scope("azps-1/Az.A/Get-A.md")
    assert Repo("y", tmp_path, "articles").in_scope("README.md")      # unrestricted repos keep every page
