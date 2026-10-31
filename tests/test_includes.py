from pathlib import Path

from docsearch.frontmatter import parse_page, split_frontmatter
from docsearch.includes import IncludeResolver


def w(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def resolve(root, rel):
    p = root / rel
    return IncludeResolver(root).resolve(p.read_text(), p)


def test_frontmatter_basic_and_crlf():
    meta, body, flags = split_frontmatter("---\r\ntitle: T\r\nms.service: x\r\n---\r\n# H\r\ntext")
    assert meta["title"] == "T" and body.startswith("# H") and not flags


def test_no_frontmatter_title_from_h1():
    pg = parse_page("# Hello\n\nbody")
    assert pg.title == "Hello" and "no_frontmatter" in pg.flags


def test_bad_frontmatter():
    assert "bad_frontmatter" in split_frontmatter("---\na: [\n---\nx")[2]


def test_nested_include_and_deps(tmp_path):
    w(tmp_path, "a/page.md", "# P\n\n[!INCLUDE [x](../includes/one.md)]\n")
    w(tmp_path, "includes/one.md", "---\nauthor: z\n---\n<!-- c -->one [!INCLUDE [y](two.md)]\n")
    w(tmp_path, "includes/two.md", "two")
    r = resolve(tmp_path, "a/page.md")
    assert "one two" in r.text and "[!INCLUDE" not in r.text and "author" not in r.text and "<!--" not in r.text
    assert r.deps == {"includes/one.md", "includes/two.md"} and not r.unresolved


def test_root_relative(tmp_path):
    w(tmp_path, "articles/p.md", "[!INCLUDE [x](~/includes/i.md)]")
    w(tmp_path, "includes/i.md", "hi")
    assert resolve(tmp_path, "articles/p.md").text == "hi"


def test_cycle_and_missing_marked_not_dropped(tmp_path):
    w(tmp_path, "p.md", "[!INCLUDE [a](a.md)]\n\n[!INCLUDE [m](nope.md)]")
    w(tmp_path, "a.md", "A [!INCLUDE [b](b.md)]")
    w(tmp_path, "b.md", "B [!INCLUDE [a](a.md)]")
    r = resolve(tmp_path, "p.md")
    assert "A B" in r.text and r.text.count("unresolved include") == 2 and len(r.unresolved) == 2


def test_include_in_code_fence_untouched(tmp_path):
    w(tmp_path, "p.md", "```md\n[!INCLUDE [a](a.md)]\n```\n")
    w(tmp_path, "a.md", "A")
    r = resolve(tmp_path, "p.md")
    assert "[!INCLUDE" in r.text and not r.deps


def test_heading_shift(tmp_path):
    w(tmp_path, "p.md", "# T\n## Sec\n[!INCLUDE [a](a.md)]\n")
    w(tmp_path, "a.md", "## Inc\ntext\n### Sub\n")
    r = resolve(tmp_path, "p.md")
    assert "### Inc" in r.text and "#### Sub" in r.text


def test_path_confinement(tmp_path):
    w(tmp_path, "outside.md", "secret")
    w(tmp_path, "repo/p.md", "[!INCLUDE [a](../outside.md)]")
    p = tmp_path / "repo/p.md"
    r = IncludeResolver(tmp_path / "repo").resolve(p.read_text(), p)
    assert "secret" not in r.text and r.unresolved
