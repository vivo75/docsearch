from pathlib import Path

from docsearch.config import Repo
from docsearch.includes import IncludeResolver
from docsearch.snippets import parse_directive, select
from docsearch.urls import Anchors, Redirects, doc_url, normalize_url, slugify

CS = """using X;
// <snippet_a>
class A {
    // <snippet_b>
    int b;
    // </snippet_b>
    int a;
}
// </snippet_a>
#region Reg
void R() {}
#endregion
"""


def test_parse_forms():
    r = parse_directive('  :::code language="csharp" source="~/x/a.cs" range="1-3,5" :::')
    assert (r.indent, r.source, r.language, r.range) == ("  ", "~/x/a.cs", "csharp", "1-3,5")
    r = parse_directive('[!code-powershell[main](~/s/a.ps1 "Title")]')
    assert (r.source, r.language) == ("~/s/a.ps1", "powershell")
    r = parse_directive("[!code-csharp[Main](~/s/a.cs?range=56-81)]")
    assert r.range == "56-81"
    r = parse_directive("[!code-csharp[Main](~/s/a.cs#snippet_a)]")
    assert r.id == "snippet_a"
    assert parse_directive("plain text") is None


def test_select_id_range_region():
    ref = parse_directive('::: code source="a" id="snippet_a" :::')
    out = select(CS, ref)
    assert "class A" in out and "int b;" in out and "snippet" not in out and "using X" not in out
    assert select(CS, parse_directive('::: code source="a" id="snippet_b" :::')) == "int b;"
    assert select(CS, parse_directive('::: code source="a" id="Reg" :::')) == "void R() {}"
    assert select(CS, parse_directive('::: code source="a" range="1,10-" :::')).startswith("using X;")
    assert select(CS, parse_directive('::: code source="a" id="nope" :::')) is None


def test_snippet_expand_via_resolver_with_corpus_sibling(tmp_path):
    (tmp_path / "repo").mkdir(); (tmp_path / "samples").mkdir()
    (tmp_path / "samples/a.cs").write_text(CS)
    pg = tmp_path / "repo/p.md"
    pg.write_text('- step\n\n  :::code language="csharp" source="~/samples/a.cs" id="snippet_b":::\n\n:::code source="~/missing/x.cs":::\n')
    r = IncludeResolver(tmp_path / "repo", tmp_path).resolve(pg.read_text(), pg)
    assert "  ```csharp\n  int b;\n  ```" in r.text
    assert r.deps == {"samples/a.cs"} and r.snippets_unresolved == ["~/missing/x.cs"]
    assert ":::code" not in r.text


def _repo(tmp_path):
    return Repo("r", tmp_path, "articles", 1.0, "https://learn.microsoft.com/azure")


def test_doc_url(tmp_path):
    r = _repo(tmp_path)
    assert doc_url(r, "articles/Storage/Blob-Intro.md") == "https://learn.microsoft.com/azure/storage/blob-intro"
    assert doc_url(r, "articles/storage/index.md") == "https://learn.microsoft.com/azure/storage"
    assert doc_url(r, "other/x.md") is None
    assert doc_url(Repo("u", tmp_path, ".", 1.0, None), "a.md") is None


def test_redirects_follow(tmp_path):
    (tmp_path / ".openpublishing.redirection.json").write_text(
        '{"redirections":[{"source_path":"articles/a/old.md","redirect_url":"/azure/a/mid"},'
        '{"source_path":"articles/a/mid.md","redirect_url":"/en-us/azure/a/new/"}]}')
    rd = Redirects.load(_repo(tmp_path))
    assert rd.follow("https://learn.microsoft.com/azure/a/old") == "https://learn.microsoft.com/azure/a/new"


def test_normalize_relative():
    assert normalize_url("../b/c", "https://learn.microsoft.com/azure/a/x") == "https://learn.microsoft.com/azure/b/c"


def test_slug():
    assert slugify("Create a `storage` account") == "create-a-storage-account"
    assert slugify("Use Microsoft.Storage/accounts (preview)") == "use-microsoftstorageaccounts-preview"
    a = Anchors()
    assert [a.make("Next steps"), a.make("Next steps")] == ["next-steps", "next-steps-1"]


def test_explicit_anchors():
    from docsearch.urls import explicit_anchors
    assert explicit_anchors("| <a name='Owner'></a>x <a id=\"b-1\">") == {"owner", "b-1"}


def test_slug_keeps_inner_underscore():
    assert slugify("Support ui_locales") == "support-ui_locales"
