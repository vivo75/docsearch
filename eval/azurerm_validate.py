"""Compare what `docsearch.azurerm_extract` reads from the provider code with what the provider docs (azurerm-docs/resources/<name>.md) say.

    python eval/azurerm_validate.py [azurerm_x ...]      (default: the ten prototype resources)

Per resource: arguments found in code vs documented (top level and nested), required/optional agreement, and for arguments that have a
documented "Possible values are `A`, `B`" list, whether the enum extracted from the code has the same set (case-insensitive)."""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from docsearch.azurerm_extract import extract  # noqa: E402

DOCS = Path(__file__).resolve().parents[3] / "azurerm-docs" / "resources"
DEFAULT = ["azurerm_mysql_flexible_server", "azurerm_kubernetes_cluster", "azurerm_storage_account", "azurerm_key_vault", "azurerm_linux_virtual_machine",
           "azurerm_virtual_network", "azurerm_postgresql_flexible_server", "azurerm_mssql_server", "azurerm_cosmosdb_account", "azurerm_service_plan",
           "azurerm_linux_web_app", "azurerm_container_app_environment"]
ARG = re.compile(r"^\*\s+`(\w+)`\s+-\s+\((Required|Optional)\)\s*(.*)$")


def documented(name: str) -> dict[str, dict]:
    p = DOCS / (name.removeprefix("azurerm_") + ".md")
    if not p.exists():
        return {}
    txt = p.read_text(encoding="utf-8")
    txt = txt.split("## Argument")[1].split("## Attribute")[0] if "## Argument" in txt else txt
    out, cur = {}, None
    for ln in txt.splitlines():
        m = ARG.match(ln.strip())
        if m:
            cur = m.group(1)
            out.setdefault(cur, {"required": m.group(2) == "Required", "text": m.group(3)})
        elif cur and ln.strip() and not ln.startswith(("*", "#")):
            out[cur]["text"] += " " + ln.strip()
    for v in out.values():
        m = re.search(r"(?:possible values (?:are|include)|valid values (?:are|include)|must be one of|one of)\s*:?\s*((?:`[^`]+`(?:,|\s|and|or|\.)*)+)", v["text"], re.I)
        v["enum"] = set(x.lower() for x in re.findall(r"`([^`]+)`", m.group(1))) if m else None
    return out


def flat(args: dict, out: dict | None = None) -> dict:
    out = {} if out is None else out
    for k, v in args.items():
        out.setdefault(k, v)
        if isinstance(v, dict) and "block" in v:
            flat(v["block"], out)
    return out


def enum_of(v: dict) -> set | None:
    val = v.get("validate") or {}
    if val.get("kind") == "enum" and val.get("values"):
        return {str(x).lower() for x in val["values"]}
    if val.get("kind") == "all":
        for o in val["of"]:
            if o.get("kind") == "enum" and o.get("values"):
                return {str(x).lower() for x in o["values"]}
    return None


rows = []
for name in (sys.argv[1:] or DEFAULT):
    r = extract(name)
    if "error" in r:
        print(f"{name}: {r['error']}"); continue
    code = flat(r["arguments"]); doc = documented(name)
    both = [k for k in doc if k in code]
    req_ok = sum(1 for k in both if "required" in code[k] or "optional" in code[k] or code[k].get("computed"))
    req_agree = sum(1 for k in both if (code[k].get("required", False) == doc[k]["required"]) or (doc[k]["required"] is False and code[k].get("optional")))
    en = [(k, enum_of(code[k]), doc[k]["enum"]) for k in both if doc[k]["enum"]]
    en_hit = [(k, c, d) for k, c, d in en if c is not None]
    en_same = [(k, c, d) for k, c, d in en_hit if c == d or d <= c or c <= d]
    rows.append({"name": name, "style": r["style"], "code_args": len(code), "doc_args": len(doc), "matched": len(both), "req_agree": req_agree,
                 "doc_enums": len(en), "enum_extracted": len(en_hit), "enum_agree": len(en_same), "api": len(r["api_calls"]), "unresolved": len(r["unresolved"]),
                 "missing_in_code": sorted(set(doc) - set(code))[:6], "only_in_code": sorted(k for k in code if k not in doc and not code[k].get("computed") and "helper" not in code[k])[:6],
                 "enum_diffs": [(k, sorted(c ^ d)[:4]) for k, c, d in en_hit if not (c == d or d <= c or c <= d)][:3]})
hdr = f"{'resource':36} {'style':8} {'code':>4} {'doc':>4} {'match':>5} {'req✓':>5} {'enum doc/ext/agree':>19} {'api':>3} {'unres':>5}"
print(hdr); print("-" * len(hdr))
for x in rows:
    print(f"{x['name']:36} {x['style']:8} {x['code_args']:>4} {x['doc_args']:>4} {x['matched']:>5} {x['req_agree']:>5} {x['doc_enums']:>6}/{x['enum_extracted']:>3}/{x['enum_agree']:>3}   {x['api']:>3} {x['unresolved']:>5}")
tot = lambda k: sum(x[k] for x in rows)
print(f"\nTOTAL matched {tot('matched')}/{tot('doc_args')} documented args; required/optional agree {tot('req_agree')}/{tot('matched')}; "
      f"documented enums {tot('doc_enums')}, extracted {tot('enum_extracted')}, agree {tot('enum_agree')}")
json.dump(rows, open(Path(__file__).parent / "results" / "azurerm-validate.json", "w"), indent=1)
for x in rows:
    if x["missing_in_code"] or x["enum_diffs"]:
        print(x["name"], "| doc-only:", x["missing_in_code"], "| enum diffs:", x["enum_diffs"])
