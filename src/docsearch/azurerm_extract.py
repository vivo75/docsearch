"""Deterministic extractor for Terraform azurerm provider objects (prototype, see docs/azurerm-extractor-design.md).

    extract("azurerm_mysql_flexible_server") -> {arguments, attributes, crud:{create,read,update,delete: {api_calls, mermaid}}, api_calls, unresolved}

Reads the Go source of `hashicorp/terraform-provider-azurerm` (a sparse clone with `internal/services/<service>` and `go.mod`) with tree-sitter and
needs no model. Enum values defined in `hashicorp/go-azure-sdk` and the REST operation behind each client call (HTTP method, path template,
API version) are read from that repository at the tag pinned by the provider's go.mod, downloaded once and cached.
Everything that cannot be resolved statically is reported in `unresolved` instead of being guessed.
"""
from __future__ import annotations

import re
import subprocess
import urllib.request
from pathlib import Path

import tree_sitter_go
from tree_sitter import Language, Node, Parser

HERE = Path(__file__).resolve().parents[2]
PROVIDER = HERE.parent.parent / "terraform-provider-azurerm"
CACHE = HERE / "data" / "azurerm-cache"
_PARSER = Parser(Language(tree_sitter_go.language()))
CRUD = ("create", "read", "update", "delete")
SDK_METHOD_NOISE = {"Get", "Create", "CreateOrUpdate", "Update", "Delete", "List", "ListByResourceGroup", "ListBySubscription"}


# ------------------------------------------------------------------ source helpers
class Src:
    def __init__(self, path: Path):
        self.path = path
        self.b = path.read_bytes()
        self.root = _PARSER.parse(self.b).root_node
        self.imports = self._imports()

    def t(self, n: Node | None) -> str:
        return self.b[n.start_byte:n.end_byte].decode("utf-8", "replace") if n is not None else ""

    def _imports(self) -> dict[str, str]:
        out = {}
        for n in self.walk(self.root, "import_spec"):
            p = self.t(n.child_by_field_name("path")).strip('"')
            alias = self.t(n.child_by_field_name("name")) or p.rsplit("/", 1)[-1]
            if re.fullmatch(r"v\d+", alias) or alias == "_":
                continue
            out[alias] = p
        return out

    @staticmethod
    def walk(n: Node, *types: str):
        stack = [n]
        while stack:
            x = stack.pop()
            if x.type in types:
                yield x
            stack.extend(reversed(x.children))

    def funcs(self) -> dict[str, Node]:
        """name (or `Recv.name` for methods) -> declaration node."""
        out = {}
        for n in self.root.children:
            if n.type == "function_declaration":
                out[self.t(n.child_by_field_name("name"))] = n
            elif n.type == "method_declaration":
                rt = re.sub(r"[*\s]", "", self.t(n.child_by_field_name("receiver")).split()[-1] if self.t(n.child_by_field_name("receiver")).split() else "")
                rt = rt.strip("()")
                out[f"{rt}.{self.t(n.child_by_field_name('name'))}"] = n
        return out


_SRC_CACHE: dict[Path, Src] = {}
_DIR_FUNCS: dict[Path, dict[str, tuple[Src, Node]]] = {}


def src_of(path: Path) -> Src:
    if path not in _SRC_CACHE:
        _SRC_CACHE[path] = Src(path)
    return _SRC_CACHE[path]


def dir_funcs(d: Path) -> dict[str, tuple[Src, Node]]:
    if d not in _DIR_FUNCS:
        out: dict[str, tuple[Src, Node]] = {}
        for g in sorted(d.glob("*.go")) if d.is_dir() else []:
            if not g.name.endswith("_test.go"):
                gs = src_of(g)
                for k, v in gs.funcs().items():
                    out.setdefault(k, (gs, v))
        _DIR_FUNCS[d] = out
    return _DIR_FUNCS[d]


def resolve_call(s: Src, call: Node, ctx: dict) -> tuple[Src, Node] | None:
    """Declaration of the function a call expression invokes: same package, or a package of the provider (`helpers.X()`)."""
    fn = s.t(call.child_by_field_name("function"))
    if "." not in fn:
        return ctx.get("pkg_funcs", {}).get(fn)
    alias, _, name = fn.partition(".")
    imp = s.imports.get(alias, "")
    if "terraform-provider-azurerm/internal/" in imp and "." not in name:
        return dir_funcs(PROVIDER / imp.split("terraform-provider-azurerm/", 1)[-1]).get(name)
    return None


def returned_literal(ent: tuple[Src, Node], want: str) -> tuple[Src, Node] | None:
    """First composite literal returned by a function whose type is a schema map (want='map') or a single schema (want='schema')."""
    fs, decl = ent
    for lit in fs.walk(decl, "composite_literal"):
        tx = fs.t(lit)
        if want == "map" and tx.startswith("map[string]*pluginsdk.Schema"):
            return fs, lit.child_by_field_name("body")
        if want == "schema" and fs.t(lit.child_by_field_name("type")).endswith(".Schema") and not tx.startswith("map["):
            return fs, lit.child_by_field_name("body")
    return None


def _lit(s: Src, n: Node | None):
    """Python value of a Go literal node when it is simple, else its source text."""
    if n is None:
        return None
    if n.type in ("interpreted_string_literal", "raw_string_literal"):
        return s.t(n)[1:-1]
    if n.type == "true":
        return True
    if n.type == "false":
        return False
    if n.type in ("int_literal", "float_literal"):
        txt = s.t(n).replace("_", "")
        try:
            return int(txt, 0) if n.type == "int_literal" else float(txt)
        except ValueError:
            return txt
    if n.type == "unary_expression" and s.t(n).startswith("-"):
        v = _lit(s, n.children[-1])
        return -v if isinstance(v, (int, float)) else s.t(n)
    return s.t(n)


def _kv(s: Src, lv: Node) -> dict[str, Node]:
    """key -> value node of a Go composite literal body (`literal_value`)."""
    out = {}
    for e in lv.children:
        if e.type == "keyed_element" and len(e.named_children) >= 2:
            k, v = e.named_children[0], e.named_children[1]
            kk = _lit(s, k.named_children[0] if k.type == "literal_element" else k)
            vv = v.named_children[0] if v.type == "literal_element" and v.named_children else v
            out[str(kk)] = vv
    return out


def _elements(lv: Node) -> list[Node]:
    return [e.named_children[0] if e.type == "literal_element" else e for e in lv.children if e.type in ("literal_element", "keyed_element")]


def _composite(n: Node | None) -> Node | None:
    """literal_value of `&T{...}`, `T{...}` or a bare `{...}`."""
    if n is None:
        return None
    if n.type == "literal_value":
        return n
    if n.type == "unary_expression":
        return _composite(n.children[-1])
    if n.type == "composite_literal":
        return n.child_by_field_name("body")
    return None


# ------------------------------------------------------------------ SDK access (enums, operations)
def tag() -> str:
    m = re.search(r"go-azure-sdk/resource-manager (v[\w.]+)", (PROVIDER / "go.mod").read_text())
    return m.group(1) if m else "main"


def provenance() -> dict:
    """Where the facts come from: repositories, pinned revisions and the license detected in each LICENSE file. No source text is included."""
    def lic(text: str) -> str:
        return "MPL-2.0" if "Mozilla Public License Version 2.0" in text else "unknown"
    rev = subprocess.run(["git", "-C", str(PROVIDER), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or None
    prov_lic = (PROVIDER / "LICENSE").read_text(encoding="utf-8", errors="replace") if (PROVIDER / "LICENSE").exists() else ""
    cached = CACHE / tag() / "LICENSE"
    if not cached.exists():
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(urllib.request.urlopen(f"https://raw.githubusercontent.com/hashicorp/go-azure-sdk/main/LICENSE", timeout=30).read().decode("utf-8"), encoding="utf-8")
        except Exception:
            cached.write_text("", encoding="utf-8")
    return {"provider": {"repo": "hashicorp/terraform-provider-azurerm", "revision": rev, "license": lic(prov_lic)},
            "sdk": {"repo": "hashicorp/go-azure-sdk", "tag": tag(), "license": lic(cached.read_text(encoding="utf-8")) if cached.exists() else "unknown"},
            "note": "facts derived from the source code; no source text is reproduced; both repositories are Mozilla Public License 2.0, copyright HashiCorp"}


def sdk_file(import_path: str, filename: str) -> str | None:
    """Text of a file of a go-azure-sdk package at the pinned tag (cached); None when it does not exist."""
    m = re.match(r"github\.com/hashicorp/go-azure-sdk/(resource-manager/.+)", import_path)
    if not m:
        return None
    rel = f"{m.group(1)}/{filename}"
    p = CACHE / tag() / rel
    if p.exists():
        return p.read_text(encoding="utf-8") or None
    url = f"https://raw.githubusercontent.com/hashicorp/go-azure-sdk/resource-manager/{tag()}/{rel}"
    try:
        text = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "docsearch-azurerm-extract"}), timeout=30).read().decode("utf-8")
    except Exception:
        text = ""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return text or None


def sdk_enum(import_path: str, type_name: str) -> list[str] | None:
    txt = sdk_file(import_path, "constants.go")
    if not txt:
        return None
    vals = re.findall(rf'^\s*\w+\s+{re.escape(type_name)}\s*=\s*"([^"]*)"', txt, re.M)
    return vals or None


def sdk_const(import_path: str, const_name: str) -> str | None:
    txt = sdk_file(import_path, "constants.go")
    m = re.search(rf'^\s*{re.escape(const_name)}\s+\w+\s*=\s*"([^"]*)"', txt or "", re.M)
    return m.group(1) if m else None


def local_const(import_path: str, const_name: str) -> str | None:
    """String constant of a package inside the provider (`internal/services/<svc>/validate`)."""
    d = PROVIDER / import_path.split("terraform-provider-azurerm/", 1)[-1]
    for f in sorted(d.glob("*.go")) if d.is_dir() else []:
        m = re.search(rf'^\s*{re.escape(const_name)}\s*(?:\w+\s*)?=\s*"([^"]*)"', f.read_text(encoding="utf-8", errors="replace"), re.M)
        if m:
            return m.group(1)
    return None


def id_template(import_path: str, id_type: str) -> str | None:
    """`/subscriptions/{subscriptionId}/.../flexibleServers/{flexibleServerName}` of an SDK resource id type."""
    stem = re.sub(r"Id$", "", id_type).lower()
    txt = sdk_file(import_path, f"id_{stem}.go")
    if not txt:
        return None
    seg = re.search(r"Segments\(\)[^{]*\{\s*return \[\]resourceids\.Segment\{(.*?)\n\t\}\n\}", txt, re.S) or re.search(r"\[\]resourceids\.Segment\{(.*?)\n\t\}", txt, re.S)
    if not seg:
        return None
    parts = []
    for kind, args in re.findall(r"resourceids\.(\w+)Segment\(([^)]*)\)", seg.group(1)):
        a = [x.strip().strip('"') for x in args.split(",")]
        if kind in ("Static", "ResourceProvider") and len(a) > 1:
            parts.append(a[1])
        elif kind == "Constant" and a:
            parts.append("{" + a[0] + "}")
        elif a:
            parts.append("{" + a[0] + "}")
    return "/" + "/".join(parts)


COMMON_IDS = {"ResourceGroupId": "/subscriptions/{subscriptionId}/resourceGroups/{resourceGroupName}", "SubscriptionId": "/subscriptions/{subscriptionId}",
              "ScopeId": "{scope}"}


def operation(import_path: str, client_type: str, method: str, version: str | None) -> dict | None:
    """REST operation behind `<Client>.<Method>` in the SDK package: HTTP method, path template, whether it is a long-running call."""
    base = re.sub(r"(CallbackThenPoll|ThenPoll)$", "", method)
    lro = base != method
    if lro:
        base = base  # the plain method file defines both Create and CreateThenPoll
    txt = sdk_file(import_path, f"method_{base.lower()}.go") or sdk_file(import_path, f"method_{base.lower()}_autorest.go")
    if not txt:
        return None
    http = re.search(r"HttpMethod:\s*http\.Method(\w+)", txt) or re.search(r"Method:\s*http\.Method(\w+)", txt)
    sig = re.search(rf"func \(c {re.escape(client_type)}\) {re.escape(base)}\(ctx context\.Context(?:, id ([\w.]+))?", txt)
    path = re.search(r"Path:\s*(.+),\n", txt)
    suffix = ""
    if path:
        f = re.search(r'fmt\.Sprintf\("%s([^"]*)"', path.group(1))
        suffix = f.group(1) if f else ""
    idt = sig.group(1) if sig else None
    tmpl = None
    if idt:
        short = idt.split(".")[-1]
        tmpl = id_template(import_path, short) if "." not in idt else COMMON_IDS.get(short)
    ver = re.search(r"/(\d{4}-\d{2}-\d{2}(?:-preview)?)/", import_path)
    return {"http_method": http.group(1).upper() if http else None, "path": (tmpl + suffix) if tmpl else (("<" + idt + ">" if idt else "") + suffix) or None,
            "api_version": ver.group(1) if ver else version, "long_running": bool(lro or "Poller" in txt), "sdk_package": import_path.split("resource-manager/")[-1]}


# ------------------------------------------------------------------ schema
_TYPES = {"TypeString": "string", "TypeInt": "int", "TypeBool": "bool", "TypeFloat": "float", "TypeList": "list", "TypeSet": "set", "TypeMap": "map"}


def parse_validate(s: Src, n: Node, ctx: dict) -> dict:
    """ValidateFunc expression -> {kind, ...}; enums are resolved through the SDK when they are not literal."""
    if n.type != "call_expression":
        return {"kind": "custom", "func": s.t(n)}
    fn = s.t(n.child_by_field_name("function"))
    args = [a for a in n.child_by_field_name("arguments").named_children]
    name = fn.split(".")[-1]
    pkg = fn.split(".")[0] if "." in fn else ""
    if name in ("StringInSlice", "StringNotInSlice", "IntInSlice") and args:
        a = args[0]
        out = {"kind": "enum", "values": None, "case_sensitive": not (len(args) > 1 and s.t(args[1]) == "true")}
        if name == "StringNotInSlice":
            out["kind"] = "not_in"
        if a.type == "composite_literal":
            vals, unres = [], []
            for e in _elements(a.child_by_field_name("body")):
                v = _lit(s, e)
                if e.type == "call_expression" and s.t(e.child_by_field_name("function")) == "string" or e.type == "selector_expression":
                    ref = s.t(e.child_by_field_name("arguments").named_children[0]) if e.type == "call_expression" else s.t(e)
                    p, _, c = ref.partition(".")
                    r = sdk_const(s.imports.get(p, ""), c) if c else None
                    if r is None and c and "internal/services" in s.imports.get(p, ""):
                        r = local_const(s.imports[p], c)
                    if r is not None:
                        vals.append(r)
                    else:
                        unres.append(ref)
                elif e.type in ("interpreted_string_literal", "raw_string_literal", "int_literal"):
                    vals.append(v)
                else:
                    unres.append(s.t(e))
            out["values"] = vals
            if unres:
                out["unresolved"] = unres
                ctx["unresolved"].append(f"enum member(s) {unres}")
        elif a.type == "call_expression":
            f2 = s.t(a.child_by_field_name("function"))
            p, _, m = f2.partition(".")
            tn = re.sub(r"^PossibleValuesFor", "", m)
            vals = sdk_enum(s.imports.get(p, ""), tn) if m.startswith("PossibleValuesFor") else None
            out["values"] = vals
            out["source"] = f2 + "()"
            if vals is None:
                ctx["unresolved"].append(f"enum {f2}()")
        else:
            out["source"] = s.t(a)
            ctx["unresolved"].append(f"enum {s.t(a)}")
        return out
    if name in ("IntBetween", "FloatBetween", "StringLenBetween", "IntAtLeast", "IntAtMost", "IntNotInSlice") and pkg == "validation":
        vals = [_lit(s, a) for a in args]
        k = {"IntAtLeast": ("min",), "IntAtMost": ("max",)}.get(name, ("min", "max"))
        return {"kind": {"IntBetween": "int_range", "FloatBetween": "float_range", "StringLenBetween": "length_range"}.get(name, name.lower()), **dict(zip(k, vals))}
    if name == "StringMatch" and args:
        rx = re.search(r"regexp\.MustCompile\((.*)\)", s.t(args[0]), re.S)
        return {"kind": "regex", "pattern": (rx.group(1).strip().strip("`\"") if rx else s.t(args[0])), "message": s.t(args[1]).strip('"') if len(args) > 1 else None}
    if name in ("All", "Any") and pkg == "validation":
        return {"kind": name.lower(), "of": [parse_validate(s, a, ctx) for a in args]}
    if pkg == "validation":
        return {"kind": "named", "func": fn}
    return custom_validator(s, fn, ctx)


def custom_validator(s: Src, fn: str, ctx: dict) -> dict:
    """`validate.X` of the same service: report the name and, when it is short, its body."""
    out = {"kind": "custom", "func": fn}
    short = fn.split(".")[-1]
    d = ctx.get("service_dir")
    if d and "." in fn:
        for f in sorted((d / "validate").glob("*.go")) if (d / "validate").is_dir() else []:
            txt = f.read_text(encoding="utf-8")
            m = re.search(rf"^func {re.escape(short)}\b.*?^\}}", txt, re.S | re.M)
            if m:
                # only derived facts: the signature line, its length and the regular expressions it compiles; never the body itself
                out["defined_in"] = f"{f.relative_to(PROVIDER).as_posix()}:{txt[:m.start()].count(chr(10)) + 1}"
                out["signature"] = m.group(0).splitlines()[0]
                out["body_lines"] = m.group(0).count("\n")
                rx = re.findall(r'regexp\.MustCompile\(((?:`[^`]*`)|(?:"[^"]*"))\)', m.group(0))
                if rx:
                    out["patterns"] = [r.strip("`\"") for r in rx]
                break
    return out


def parse_schema_map(s: Src, lv: Node, ctx: dict) -> dict:
    out = {}
    for name, v in _kv(s, lv).items():
        body = _composite(v)
        if body is not None and v.type != "call_expression":
            out[name] = parse_schema_entry(s, body, ctx)
        elif v.type == "call_expression":
            ent = resolve_call(s, v, ctx)
            got = returned_literal(ent, "schema") if ent else None
            if got:
                resolved = parse_schema_entry(got[0], got[1], ctx); resolved["via"] = s.t(v.child_by_field_name("function")) + "()"
                out[name] = resolved
            else:
                out[name] = {"helper": s.t(v), **helper_hint(s.t(v))}
        else:
            out[name] = {"ref": s.t(v)}
            ctx["unresolved"].append(f"argument {name}: {s.t(v)}")
    return out


def helper_hint(call: str) -> dict:
    """A few well known shared schema helpers (internal/tf/pluginsdk, commonschema)."""
    c = call.split("(")[0]
    known = {"commonschema.ResourceGroupName": {"type": "string", "required": True, "force_new": True},
             "commonschema.ResourceGroupNameForDataSource": {"type": "string", "required": True},
             "commonschema.Location": {"type": "string", "required": True, "force_new": True},
             "commonschema.LocationOptional": {"type": "string", "optional": True, "force_new": True},
             "commonschema.LocationComputed": {"type": "string", "computed": True},
             "tags.Schema": {"type": "map", "optional": True}, "commonschema.Tags": {"type": "map", "optional": True},
             "commonschema.TagsDataSource": {"type": "map", "computed": True}}
    m = re.match(r"commonschema\.(SystemAssigned|UserAssigned|SystemOrUserAssigned|SystemAssignedUserAssigned)Identity(Optional|Required|Computed|ForceNew\w*|Optional\w*)?", c)
    if m and "Computed" not in c:
        kind = m.group(1)
        vals = {"SystemAssigned": ["SystemAssigned"], "UserAssigned": ["UserAssigned"], "SystemOrUserAssigned": ["SystemAssigned", "UserAssigned"],
                "SystemAssignedUserAssigned": ["SystemAssigned", "UserAssigned", "SystemAssigned, UserAssigned"]}[kind]
        blk = {"type": {"type": "string", "required": True, "validate": {"kind": "enum", "values": vals, "source": c + " (helper)"}}}
        if "UserAssigned" in kind:
            blk["identity_ids"] = {"type": "set", "optional": True, "elem": {"type": "string"}}
        blk["principal_id"] = {"type": "string", "computed": True}
        blk["tenant_id"] = {"type": "string", "computed": True}
        return {"type": "list", "max_items": 1, "required": "Required" in c, "optional": "Required" not in c, "block": blk}
    return known.get(c, {})


def parse_schema_entry(s: Src, lv: Node, ctx: dict) -> dict:
    f = _kv(s, lv)
    e: dict = {}
    if "Type" in f:
        e["type"] = _TYPES.get(s.t(f["Type"]).split(".")[-1], s.t(f["Type"]))
    for k, out in (("Required", "required"), ("Optional", "optional"), ("Computed", "computed"), ("ForceNew", "force_new"), ("Sensitive", "sensitive"),
                   ("WriteOnly", "write_only")):
        if k in f and _lit(s, f[k]) is True:
            e[out] = True
    for k, out in (("Default", "default"), ("MinItems", "min_items"), ("MaxItems", "max_items"), ("Deprecated", "deprecated")):
        if k in f:
            e[out] = _lit(s, f[k])
    if "ValidateFunc" in f:
        e["validate"] = parse_validate(s, f["ValidateFunc"], ctx)
    if "DiffSuppressFunc" in f:
        e["diff_suppress"] = s.t(f["DiffSuppressFunc"])[:80]
    for k in ("ConflictsWith", "ExactlyOneOf", "RequiredWith", "AtLeastOneOf"):
        if k in f and (body := _composite(f[k])):
            e[re.sub(r"(?<!^)([A-Z])", r"_\1", k).lower()] = [str(_lit(s, x)) for x in _elements(body)]
    if "Elem" in f:
        body = _composite(f["Elem"])
        if body is not None:
            t = s.t(f["Elem"].named_children[-1].child_by_field_name("type")) if f["Elem"].type == "unary_expression" and f["Elem"].named_children[-1].type == "composite_literal" else ""
            inner = _kv(s, body)
            sv = inner.get("Schema")
            if sv is not None and sv.type == "call_expression" and t.endswith("Resource"):
                ent = resolve_call(s, sv, ctx)
                got = returned_literal(ent, "map") if ent else None
                if got:
                    e["block"] = parse_schema_map(got[0], got[1], ctx)
                else:
                    ctx["unresolved"].append(f"nested schema {s.t(sv)[:50]}")
            elif "Schema" in inner and (m := _composite(inner["Schema"])) is not None and t.endswith("Resource"):
                e["block"] = parse_schema_map(s, m, ctx)
            else:
                e["elem"] = parse_schema_entry(s, body, ctx)
    return e


# ------------------------------------------------------------------ locating the object
def find_object(name: str, kind: str = "resource") -> tuple[Path, str, str] | None:
    """-> (go file, style 'typed'|'untyped', entry: constructor function name or receiver type). kind: 'resource' | 'data_source'."""
    svc = PROVIDER / "internal" / "services"
    key = f'"{name}"'
    suffix = "_resource.go" if kind == "resource" else "_data_source.go"
    for f in sorted(svc.rglob("*.go")):
        if f.name.endswith("_test.go"):
            continue
        txt = f.read_text(encoding="utf-8", errors="replace")
        if key not in txt:
            continue
        if f.name != "registration.go" and not f.name.endswith(suffix):
            continue
        m = re.search(rf"func \((?:\w+ )?(\*?\w+)\) ResourceType\(\) string \{{\s*return {re.escape(key)}", txt)
        if m:
            return f, "typed", m.group(1).lstrip("*")
        if f.name == "registration.go":
            section = re.search(r"SupportedResources\(\).*?\n\}" if kind == "resource" else r"SupportedDataSources\(\).*?\n\}", txt, re.S)
            m = re.search(rf'{re.escape(key)}:\s*([A-Za-z0-9_]+)\(\)', section.group(0) if section else "")
            if m:
                ctor = m.group(1)
                for g in sorted(f.parent.glob("*.go")):
                    if not g.name.endswith("_test.go") and re.search(rf"^func {ctor}\(", g.read_text(encoding="utf-8", errors="replace"), re.M):
                        return g, "untyped", ctor
            m2 = re.search(rf'{re.escape(key)}:\s*(\w+)\.Register(Resource|DataSource)\(\)', section.group(0) if section else "")
            if m2:                                                         # newer layout: <service>/resources/<name>/resource.go
                imp = Src(f).imports.get(m2.group(1), "")
                d = PROVIDER / imp.split("terraform-provider-azurerm/", 1)[-1]
                for g in sorted(d.glob("*.go")) if d.is_dir() else []:
                    if not g.name.endswith("_test.go") and re.search(rf"^func Register{m2.group(2)}\(", g.read_text(encoding="utf-8", errors="replace"), re.M):
                        return g, "untyped", f"Register{m2.group(2)}"
    return None


# ------------------------------------------------------------------ client / API calls
def service_clients(service_dir: Path) -> dict[str, tuple[str, str]]:
    """field name of the service client struct -> (sdk import path, client type)."""
    p = service_dir / "client" / "client.go"
    if not p.exists():
        return {}
    s = Src(p)
    out = {}
    for fld in s.walk(s.root, "field_declaration"):
        nm = s.t(fld.child_by_field_name("name"))
        ty = s.t(fld.child_by_field_name("type")).lstrip("*")
        if "." in ty:
            alias, tn = ty.split(".", 1)
            if alias in s.imports:
                imp = s.imports[alias]
                if re.search(r"/\d{4}-\d{2}-\d{2}(-preview)?$", imp) and tn == "Client":     # a meta client: one field per API group
                    for sub, (p2, t2) in meta_client(imp).items():
                        out[f"{nm}.{sub}"] = (p2, t2)
                        out.setdefault(sub, (p2, t2))
                else:
                    out[nm] = (imp, tn)
    return out


def meta_client(import_path: str) -> dict[str, tuple[str, str]]:
    txt = sdk_file(import_path, "client.go") or ""
    imps = {p.rsplit("/", 1)[-1]: p for p in re.findall(r'"(github\.com/hashicorp/go-azure-sdk/[^"]+)"', txt)}
    return {f: (imps[pk], t) for f, pk, t in re.findall(r"^\s*(\w+)\s+\*(\w+)\.(\w+)\s*$", txt, re.M) if pk in imps}


def calls_in(s: Src, body: Node, clients: dict, helpers: set[str], ctx: dict) -> list[dict]:
    """Ordered API calls and helper calls inside a function body."""
    var_chain: dict[str, str] = {}
    for a in s.walk(body, "short_var_declaration", "assignment_statement"):
        left, right = a.child_by_field_name("left"), a.child_by_field_name("right")
        if left is None or right is None:
            continue
        rt = re.sub(r"\.\(\*?[\w.]+\)", "", s.t(right))             # meta.(*clients.Client).X.Y -> meta.X.Y
        chain = re.findall(r"\.(\w+)", rt.split("(")[0]) if re.search(r"[Cc]lient", s.t(right)) else []
        if chain and len(left.named_children) == 1:
            var_chain[s.t(left.named_children[0])] = chain[-1]
    out = []
    for c in sorted(s.walk(body, "call_expression"), key=lambda n: n.start_byte):
        fn = c.child_by_field_name("function")
        if fn is None:
            continue
        if fn.type == "selector_expression":
            recv, method = fn.child_by_field_name("operand"), s.t(fn.child_by_field_name("field"))
            rname = s.t(recv)
            field = var_chain.get(rname) or (re.findall(r"\.(\w+)$", rname) or [""])[0]
            if field in clients:
                imp, ctype = clients[field]
                op = operation(imp, ctype, method, None)
                if op:
                    out.append({"kind": "api", "client": f"{imp.rsplit('/', 1)[-1]}.{ctype}", "method": method, **op, "pos": c.start_byte})
                else:
                    ctx["unresolved"].append(f"client call {field}.{method}")
        elif fn.type == "identifier":
            nm = s.t(fn)
            if nm in helpers:
                out.append({"kind": "helper", "name": nm, "pos": c.start_byte})
    return out


def api_summary(calls: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in calls:
        if c["kind"] == "api":
            k = (c["http_method"], c["path"], c["api_version"])
            if k not in seen:
                seen.add(k)
                out.append({k2: v for k2, v in c.items() if k2 not in ("kind", "pos")})
    return out


# ------------------------------------------------------------------ flow diagram
def _short(txt: str, n: int = 46) -> str:
    txt = re.sub(r"\s+", " ", txt).strip().replace('"', "'")
    return txt if len(txt) <= n else txt[: n - 1] + "…"


def mermaid(s: Src, body: Node, clients: dict, helpers: set[str], title: str, ctx: dict, cap: int = 60) -> str:
    nodes: list[str] = []
    edges: list[str] = []

    def nid() -> str:
        return f"n{len(nodes)}"

    def add(label: str, shape: str = "[]") -> str:
        i = nid()
        a, b = ("[", "]") if shape == "[]" else ("{", "}") if shape == "{}" else ("([", "])")
        nodes.append(f'    {i}{a}"{label}"{b}')
        return i

    def step_calls(n: Node) -> list[str]:
        out = []
        for c in calls_in(s, n, clients, helpers, {"unresolved": []}):
            out.append((f"{c['http_method'] or '?'} {c['client'].split('.')[0]}.{c['method']}" if c["kind"] == "api" else f"{c['name']}()"))
        return out

    def seq(block: Node, prev: str, edge_label: str = "") -> str:
        for st in block.named_children:
            if len(nodes) >= cap:
                return prev
            if st.type == "if_statement":
                cond = st.child_by_field_name("condition")
                ctext = s.t(cond)
                init = st.child_by_field_name("initializer")
                if init is not None:
                    for lab in step_calls(init):
                        n = add(lab); edges.append(f"    {prev} -->{('|' + edge_label + '|') if edge_label else ''} {n}"); prev, edge_label = n, ""
                cons = st.child_by_field_name("consequence")
                alt = st.child_by_field_name("alternative")
                if re.search(r"err\s*!=\s*nil", ctext) and not step_calls(cons):
                    continue                                              # plain error handling: not part of the flow
                if not step_calls(cons) and not (alt is not None and step_calls(alt)):
                    continue
                d = add(_short(ctext), "{}"); edges.append(f"    {prev} -->{('|' + edge_label + '|') if edge_label else ''} {d}")
                end_yes = seq(cons, d, "yes")
                join = add("·", "()")
                edges.append(f"    {end_yes} --> {join}")
                if alt is not None and alt.type == "block":
                    end_no = seq(alt, d, "no"); edges.append(f"    {end_no} --> {join}")
                else:
                    edges.append(f"    {d} -->|no| {join}")
                prev, edge_label = join, ""
            elif st.type in ("for_statement", "range_clause"):
                labs = step_calls(st)
                if labs:
                    n = add("for each: " + "; ".join(dict.fromkeys(labs))); edges.append(f"    {prev} -->{('|' + edge_label + '|') if edge_label else ''} {n}"); prev, edge_label = n, ""
            elif st.type in ("block", "statement_list"):
                prev = seq(st, prev, edge_label); edge_label = ""
            else:
                labs = list(dict.fromkeys(step_calls(st)))
                if labs:
                    n = add("; ".join(labs)); edges.append(f"    {prev} -->{('|' + edge_label + '|') if edge_label else ''} {n}"); prev, edge_label = n, ""
        return prev

    start = add(title, "()")
    stmts = next((c for c in body.children if c.type == "statement_list"), body)
    last = seq(stmts, start)
    end = add("done", "()")
    edges.append(f"    {last} --> {end}")
    if len(nodes) >= cap:
        ctx["unresolved"].append(f"flow {title} truncated at {cap} nodes")
    return "flowchart TD\n" + "\n".join(nodes + edges)


# ------------------------------------------------------------------ public
def extract(name: str, kind: str = "resource") -> dict:
    found = find_object(name, kind)
    if not found:
        return {"error": f"{name}: not found in the provider checkout ({PROVIDER})"}
    path, style, entry = found
    s = Src(path)
    svc_dir = PROVIDER / "internal" / "services" / path.relative_to(PROVIDER / "internal" / "services").parts[0]
    ctx: dict = {"unresolved": [], "service_dir": svc_dir}
    pkg_funcs: dict[str, tuple[Src, Node]] = {}
    for g in sorted(path.parent.glob("*.go")):
        if g.name.endswith("_test.go"):
            continue
        gs = s if g == path else Src(g)
        for k, v in gs.funcs().items():
            pkg_funcs.setdefault(k, (gs, v))
    helpers = {k for k in pkg_funcs if "." not in k and re.match(r"(expand|flatten)", k)}
    ctx["pkg_funcs"] = pkg_funcs
    clients = service_clients(svc_dir)
    out: dict = {"resource": name, "style": style, "defined_in": str(path.relative_to(PROVIDER)), "provenance": provenance(), "arguments": {}, "attributes": [], "crud": {}}
    bodies: dict[str, tuple[Src, Node]] = {}
    if style == "typed":
        for meth, key in (("Arguments", "arguments"), ("Attributes", "attributes")):
            ent = pkg_funcs.get(f"{entry}.{meth}")
            if ent:
                for lit in ent[0].walk(ent[1], "composite_literal"):
                    if ent[0].t(lit).startswith("map[string]*pluginsdk.Schema"):
                        m = parse_schema_map(ent[0], lit.child_by_field_name("body"), ctx)
                        if key == "arguments":
                            out["arguments"] = m
                        else:
                            out["attributes"] = sorted(m)
                        break
        for c in CRUD:
            ent = pkg_funcs.get(f"{entry}.{c.capitalize()}")
            if ent:
                bodies[c] = (ent[0], ent[1].child_by_field_name("body"))
    else:
        ctor = pkg_funcs.get(entry)
        res = None
        for lit in s.walk(ctor[1], "composite_literal"):
            if s.t(lit.child_by_field_name("type")).endswith("Resource"):
                res = _kv(s, lit.child_by_field_name("body")); break
        if res is None:
            out["error"] = "resource literal not found"; return out
        sch = res.get("Schema")
        lv, ls = (_composite(sch) if sch is not None and sch.type != "call_expression" else None), s
        if lv is None and sch is not None and sch.type == "call_expression":
            ent = resolve_call(s, sch, ctx)
            got = returned_literal(ent, "map") if ent else None
            if got:
                ls, lv = got                                                                  # the literal belongs to the file that defines the function
        if lv is not None:
            out["arguments"] = parse_schema_map(ls, lv, ctx)
        for c in CRUD:
            for key in (c.capitalize(), c.capitalize() + "Context"):
                if key in res:
                    ent = pkg_funcs.get(s.t(res[key]))
                    if ent:
                        bodies[c] = (ent[0], ent[1].child_by_field_name("body")); break
    allcalls: list[dict] = []
    for c, (bs, body) in bodies.items():
        calls = calls_in(bs, body, clients, helpers, ctx)
        allcalls += calls
        out["crud"][c] = {"api_calls": api_summary(calls), "helpers": sorted({x["name"] for x in calls if x["kind"] == "helper"}),
                          "mermaid": mermaid(bs, body, clients, helpers, f"{c} {name}", ctx)}
    out["api_calls"] = api_summary(allcalls)
    out["unresolved"] = sorted(set(ctx["unresolved"]))
    return out
