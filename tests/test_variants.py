from docsearch.variants import split_variants


def tabs_of(segs):
    return [(s.variant.tabs, s.variant.pivots, s.variant.monikers, s.text.strip()) for s in segs]


def test_tabs_close_on_hr_and_heading():
    t = "# T\nintro\n\n## [Portal](#tab/portal)\nstep p\n\n## [CLI](#tab/cli)\nstep c\n\n---\n\nafter\n## Next\nmore"
    segs = split_variants(t)
    got = [(s.variant.tabs, s.text) for s in segs]
    assert ((), "# T\nintro\n") == got[0]
    assert got[1][0] == ("portal",) and "step p" in got[1][1] and "## Portal" in got[1][1]
    assert got[2][0] == ("cli",) and "step c" in got[2][1]
    assert got[3][0] == () and "after" in got[3][1] and "---" not in got[3][1]
    assert "tab/" not in "".join(s.text for s in segs)


def test_nested_tab_levels():
    t = "## [A](#tab/a)\nxa\n### [B](#tab/b)\nxb\n---\nback in a\n---\nout"
    segs = split_variants(t)
    assert [s.variant.tabs for s in segs] == [("a",), ("a", "b"), ("a",), ()]


def test_pivot_and_moniker_and_zone_closes_tabs():
    t = ('intro\n::: zone pivot="cli"\n#### [One](#tab/one)\nin one\n::: zone-end\n'
         'tail\n::: moniker range=">= aspnetcore-6.0"\nnew\n::: moniker-end\nend')
    r = tabs_of(split_variants(t))
    assert r[0][:3] == ((), (), ()) and r[1][:3] == (("one",), ("cli",), ())
    assert r[2][:3] == ((), (), ()) and "tail" in r[2][3]
    assert r[3][:3] == ((), (), (">= aspnetcore-6.0",)) and r[3][3] == "new"
    assert r[4][3] == "end"


def test_fenced_directives_ignored():
    t = "```md\n::: zone pivot=\"x\"\n## [A](#tab/a)\n```\nplain"
    segs = split_variants(t)
    assert len(segs) == 1 and segs[0].variant.is_shared and "zone pivot" in segs[0].text


def test_hr_without_tabs_is_kept():
    assert "---" in split_variants("a\n\n---\n\nb")[0].text


def test_indented_tab_heading_in_list():
    segs = split_variants("1. Do it\n\n   # [PowerShell](#tab/powershell)\n   run x\n\n   ---\n\n2. Next")
    assert [s.variant.tabs for s in segs] == [(), ("powershell",), ()]
    assert "tab/" not in "".join(s.text for s in segs)
