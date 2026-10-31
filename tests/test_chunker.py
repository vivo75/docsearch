import re

from docsearch.chunker import HARD_CAP, DocInfo, chunk_page, count_tokens

D = DocInfo("r", "a/p.md", "My Page")


def words(n, w="word"):
    return " ".join(f"{w}{i}" for i in range(n))


def chunks(text):
    return chunk_page(D, text)


def test_h2_boundaries_and_breadcrumb():
    t = f"# My Page\n\nintro {words(150)}\n\n## Alpha\n\n{words(150)}\n\n## Beta\n\n{words(150)}\n"
    cs = chunks(t)
    assert [c.heading_path for c in cs] == [(), ("Alpha",), ("Beta",)]
    assert cs[1].anchor == "alpha" and cs[2].breadcrumb == "My Page › Beta"
    assert not cs[1].text.startswith("## Alpha")           # own heading is breadcrumb, not body
    assert "My Page › Alpha" in cs[1].embed_text


def test_small_sections_merge_into_previous():
    t = f"# My Page\n\n## Alpha\n\n{words(200)}\n\n## Next steps\n\n- [a](b.md)\n"
    cs = chunks(t)
    assert len(cs) == 1 and "## Next steps" in cs[0].text


def test_variants_never_merge_and_carry_preamble():
    t = (f"# My Page\n\n## Create\n\nChoose a tool to create it.\n\n"
         f"### [Portal](#tab/portal)\n\nUse portal {words(60)}\n\n### [CLI](#tab/cli)\n\nUse cli {words(60)}\n\n---\n\n## After\n\nshared {words(120)}")
    cs = chunks(t)
    tabs = [c.variant.tabs for c in cs]
    assert ("portal",) in tabs and ("cli",) in tabs
    for c in cs:
        assert not ("Use portal" in c.text and "Use cli" in c.text)
    cli = next(c for c in cs if c.variant.tabs == ("cli",))
    assert "Choose a tool" in cli.context and "Choose a tool" in cli.embed_text
    assert cs[-1].variant.is_shared and "shared" in cs[-1].text


def test_oversize_code_split_keeps_fences():
    code = "\n".join(f"line_{i} = compute({i}, 'x')" for i in range(400))
    cs = chunks(f"# My Page\n\n## Code\n\n```python\n{code}\n```\n")
    assert len(cs) > 1
    for c in cs:
        assert c.text.startswith("```python") and c.text.rstrip().endswith("```") and c.token_count <= HARD_CAP + 20
    assert "".join(re.findall(r"line_(\d+)", " ".join(c.text for c in cs))) == "".join(str(i) for i in range(400))


def test_oversize_table_repeats_header():
    rows = "\n".join(f"| name{i} | value {i} {words(10)} |" for i in range(200))
    cs = chunks(f"# My Page\n\n## T\n\n| a | b |\n|---|---|\n{rows}\n")
    assert len(cs) > 1 and all(c.text.startswith("| a | b |\n|---|---|") for c in cs)


def test_procedure_stays_whole_when_it_fits():
    steps = "\n".join(f"{i}. Step {i} {words(30)}" for i in range(1, 8))
    cs = chunks(f"# My Page\n\n## Do it\n\n{steps}\n")
    assert len(cs) == 1 and cs[0].text.count("Step ") == 7


def test_indented_fence_in_list_is_not_headings():
    t = "# My Page\n\n## S\n\n1. Run:\n\n   ```bash\n   # a comment, not a heading\n   az x\n   ```\n\n2. Done\n"
    cs = chunks(t)
    assert len(cs) == 1 and "# a comment" in cs[0].text and cs[0].heading_path == ("S",)


def test_ids_stable_and_links():
    t = f"# My Page\n\n## A\n\n{words(500)}\n\n{words(500)}\n\n## B\n\n{words(150)}\n"
    a, b = chunks(t), chunks(t)
    assert [c.chunk_id for c in a] == [c.chunk_id for c in b] and len({c.chunk_id for c in a}) == len(a)
    assert a[0].next_id == a[1].chunk_id and a[1].prev_id == a[0].chunk_id
    assert a[1].parent_id == a[0].chunk_id and a[0].prev_id == ""


def test_prerequisites_attached_to_next_section():
    t = (f"# My Page\n\n## Prerequisites\n\nYou need an account and the CLI. {words(55)}\n\n"
         f"## Create\n\n{words(200)}\n")
    cs = chunks(t)
    create = next(c for c in cs if c.heading_path == ("Create",))
    assert "Prerequisites: You need an account" in create.context


def test_no_text_lost():
    paras = [f"para{i} " + words(80, f"p{i}w") for i in range(30)]
    t = "# My Page\n\n## S\n\n" + "\n\n".join(paras)
    joined = " ".join(c.text for c in chunks(t))
    assert all(p.split()[0] in joined and p.split()[-1] in joined for p in paras)
    assert count_tokens("") == 0


def test_oversize_list_item_with_code_keeps_fences_balanced():
    code = "\n".join(f"   cmd_{i} --flag value_{i}" for i in range(500))
    cs = chunks(f"# My Page\n\n## S\n\n1. Run it:\n\n   ```bash\n{code}\n   ```\n\n2. Done\n")
    assert len(cs) > 2 and max(c.token_count for c in cs) <= HARD_CAP + 60
    for c in cs:
        assert c.text.count("```") % 2 == 0


def test_pipeline_end_to_end(tmp_path):
    from docsearch.config import Config, Repo
    from docsearch.pipeline import Processor
    (tmp_path / "r/articles/s").mkdir(parents=True); (tmp_path / "r/includes").mkdir()
    (tmp_path / "r/includes/i.md").write_text("Shared **text**. [other](../s/o.md#x)")
    (tmp_path / "r/articles/s/p.md").write_text(
        "---\ntitle: Pg\nms.service: svc\n---\n# Pg\n\n## One\n\n[!INCLUDE [i](../../includes/i.md)]\n\n"
        '<!-- hidden -->\n:::image type="content" source="a.png" alt-text="Shot":::\n')
    repo = Repo("r", tmp_path / "r", "articles", 1.0, "https://learn.microsoft.com/azure")
    r = Processor(Config(tmp_path, (repo,)), repo).process("articles/s/p.md")
    assert r.doc.url == "https://learn.microsoft.com/azure/s/p" and r.meta["ms.service"] == "svc"
    t = r.chunks[0].text
    assert "Shared **text**" in t and "[Image: Shot]" in t and "hidden" not in t
    assert "(https://learn.microsoft.com/azure/s/o#x)" in t and r.deps == {"r/includes/i.md"}


def test_single_giant_line_is_split():
    blob = " ".join(f"[{i}.5, {i}.25]" for i in range(3000))
    cs = chunks(f"# My Page\n\n## S\n\n```json\n{blob}\n```\n")
    assert len(cs) > 3 and max(c.token_count for c in cs) <= HARD_CAP + 60
    assert all(c.text.count("```") % 2 == 0 for c in cs)


def test_longer_fence_not_closed_by_shorter():
    from docsearch.markdown import fence_mask
    assert fence_mask(["````md", "```", "x", "```", "````", "after"]) == [True] * 5 + [False]


def test_unbreakable_long_string_is_split():
    blob = "https://x.test/?q=" + "%2C" .join(f"a{i}" for i in range(4000))
    cs = chunks(f"# My Page\n\n## S\n\nSee {blob}.\n")
    assert len(cs) > 3 and max(c.token_count for c in cs) <= HARD_CAP + 60


def test_html_stripped_from_heading_path():
    cs = chunks(f'# My Page\n\n## <a name="x"></a>Command `az x`\n\n{words(150)}\n')
    assert cs[0].heading_path == ("Command `az x`",)


def test_embed_text_matches_build_helper():
    from docsearch.build import embed_text
    t = f"# My Page\n\n## Create\n\nChoose a tool.\n\n### [CLI](#tab/cli)\n\nUse cli {words(60)}\n"
    for c in chunks(t):
        assert embed_text(c.doc.title, " › ".join(c.heading_path), c.context, c.text) == c.embed_text
