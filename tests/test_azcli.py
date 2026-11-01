from pathlib import Path

from docsearch.azcli import to_markdown
from docsearch.config import load_config
from docsearch.frontmatter import parse_page
from docsearch.sync import is_page

YML = """### YamlMime:AzureCLIGroup
uid: az_ts
name: az ts
summary: |-
  Manage template specs.
status: GA
sourceType: Core
commands:
- az_ts_create
directCommands:
- uid: az_ts_create
  name: az ts create
  summary: Create a template spec.
  status: GA
  sourceType: Core
  isPreview: true
  syntax: az ts create --name	--resource-group
  examples:
  - summary: Create one.
    syntax: az ts create -g rg -n spec
  requiredParameters:
  - name: --name -n
    summary: The name.
  optionalParameters:
  - name: --tags
    summary: Space-separated tags.
  - name: --debug
    summary: Increase logging verbosity.
    groupName: Global Arguments
  globalParameters:
  - name: --only-show-errors
    summary: Only show errors.
"""


def test_to_markdown_structure():
    md = to_markdown(YML)                      # the literal tab in `syntax` must not break parsing
    page = parse_page(md)
    assert page.title == "az ts" and page.meta.get("ms.topic") == "reference"
    assert "## az ts create" in md and "Status: Preview" in md
    assert "az ts create -g rg -n spec" in md and "`--name -n`: The name." in md and "`--tags`" in md
    assert "--debug" not in md and "--only-show-errors" not in md     # global parameters dropped


def test_is_page_by_format():
    assert is_page("latest/ts.yml", "azcli-yaml") and not is_page("latest/TOC.yml", "azcli-yaml")
    assert not is_page("latest/ts.yml") and is_page("articles/a.md") and not is_page("articles/a.md", "azcli-yaml")


def test_config_shared_checkout(tmp_path: Path):
    (tmp_path / "repos.toml").write_text('root = "corpus"\n'
        '[[repo]]\nname = "cli-docs"\npath = "azure-docs-cli"\ndocs_root = "c"\n'
        '[[repo]]\nname = "cli-ref"\npath = "azure-docs-cli"\ndocs_root = "r"\nformat = "azcli-yaml"\n')
    cfg = load_config(tmp_path / "repos.toml")
    a, b = cfg.repo("cli-docs"), cfg.repo("cli-ref")
    assert a.path == b.path == (tmp_path / "corpus" / "azure-docs-cli").resolve()
    assert (a.fmt, b.fmt) == ("md", "azcli-yaml")


def test_malformed_or_non_mapping_yaml_is_skipped(tmp_path: Path):
    from docsearch.pipeline import Processor
    assert to_markdown("a: [1, 2\n  b: :") is None          # YAML syntax error
    assert to_markdown("- a\n- b") is None                   # a list, not a command group
    assert to_markdown("just a string") is None
    repo = tmp_path / "corpus" / "cli"
    (repo / "ref").mkdir(parents=True)
    (repo / "ref" / "bad.yml").write_text("- not\n- a group\n")
    (repo / "ref" / "ok.yml").write_text(YML)
    (tmp_path / "repos.toml").write_text('root = "corpus"\n[[repo]]\nname = "cli-ref"\npath = "cli"\ndocs_root = "ref"\nformat = "azcli-yaml"\n')
    cfg = load_config(tmp_path / "repos.toml")
    p = Processor(cfg, cfg.repo("cli-ref"))
    assert p.process("ref/bad.yml") is None
    assert p.process("ref/ok.yml").doc.title == "az ts"
