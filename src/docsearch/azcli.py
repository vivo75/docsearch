"""Azure CLI reference YAML (MicrosoftDocs/azure-docs-cli docs-ref-autogen, `### YamlMime:AzureCLIGroup`) -> Markdown page.

One file = one command group. The page gets frontmatter (title = group name, ms.topic = reference) and one `##` section per
command: summary, status, syntax, examples, required and optional parameters. Global parameters (identical on every command)
are left out. Some files contain literal tabs, which YAML forbids; they are replaced by spaces before parsing.
"""
from __future__ import annotations

import yaml


def _clean(s) -> str:
    return (s or "").strip()


def _status(c: dict) -> str:
    flags = [w for k, w in (("isPreview", "Preview"), ("isExperimental", "Experimental"), ("isDeprecated", "Deprecated")) if c.get(k)]
    ext = " (extension)" if "Extension" in (c.get("sourceType") or "") and "Core" not in (c.get("sourceType") or "") else ""
    return ", ".join(flags) + ext if flags or ext else ""


def _params(title: str, ps: list[dict] | None) -> list[str]:
    ps = [p for p in ps or [] if "global" not in (p.get("groupName") or "").lower()]
    if not ps:
        return []
    out = [f"### {title}", ""]
    for p in ps:
        extra = []
        if p.get("defaultValue") not in (None, ""):
            extra.append(f"default: `{p['defaultValue']}`")
        if p.get("parameterValueGroup"):
            extra.append(f"values: {p['parameterValueGroup']}")
        out.append(f"- `{p.get('name', '')}`: {_clean(p.get('summary'))}" + (f" ({'; '.join(extra)})" if extra else ""))
        if _clean(p.get("description")):
            out.append(f"  {_clean(p['description'])}")
    return out + [""]


def to_markdown(raw: str) -> str:
    d = yaml.safe_load(raw.replace("\t", " ")) or {}
    name = d.get("name") or d.get("uid", "").replace("_", " ")
    summary = _clean(d.get("summary"))
    L = ["---", f"title: {yaml.safe_dump(name, default_style='\"').strip()}",
         f"description: {yaml.safe_dump(summary.splitlines()[0] if summary else name, default_style='\"', width=10**6).strip()}",
         "ms.topic: reference", "---", "", f"# {name}", ""]
    if summary:
        L += [summary, ""]
    if _clean(d.get("description")):
        L += [_clean(d["description"]), ""]
    if _status(d):
        L += [f"Status: {_status(d)}", ""]
    subs = [c.replace("_", " ") for c in d.get("commands") or [] if isinstance(c, str)]
    if subs:
        L += ["Commands and subgroups: " + ", ".join(f"`{s}`" for s in subs[:80]) + (" ..." if len(subs) > 80 else ""), ""]
    for c in d.get("directCommands") or []:
        L += [f"## {c.get('name', '')}", ""]
        if _clean(c.get("summary")):
            L += [_clean(c["summary"]), ""]
        if _clean(c.get("description")):
            L += [_clean(c["description"]), ""]
        if _status(c):
            L += [f"Status: {_status(c)}", ""]
        if _clean(c.get("syntax")):
            L += ["```azurecli", _clean(c["syntax"]), "```", ""]
        ex = c.get("examples") or []
        if ex:
            L += ["### Examples", ""]
            for e in ex:
                L += [_clean(e.get("summary")), "", "```azurecli", _clean(e.get("syntax")), "```", ""]
        L += _params("Required parameters", c.get("requiredParameters"))
        L += _params("Optional parameters", c.get("optionalParameters"))
    return "\n".join(L)
