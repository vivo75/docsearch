import json

from docsearch.docfxmeta import file_metadata


def test_file_metadata_globs(tmp_path):
    fm = {"ms.service": {"articles/aks/**/*.md": "azure-kubernetes-service", "articles/aks-hybrid-edge/**/*.md": "hybrid"},
          "ms.subservice": {"articles/aks/*.md": "top"}}
    (tmp_path / "docfx.json").write_text(json.dumps({"build": {"fileMetadata": fm}}))
    assert file_metadata(tmp_path, "articles/aks/x.md") == {"ms.service": "azure-kubernetes-service", "ms.subservice": "top"}
    assert file_metadata(tmp_path, "articles/aks/a/b/x.md") == {"ms.service": "azure-kubernetes-service"}
    assert file_metadata(tmp_path, "articles/aks-hybrid-edge/bare-metal/x.md") == {"ms.service": "hybrid"}
    assert file_metadata(tmp_path, "articles/other/x.md") == {}


def test_no_docfx(tmp_path):
    assert file_metadata(tmp_path, "a.md") == {}
