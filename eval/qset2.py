"""Second, larger eval question set (target 600 answerable + 60 unanswerable). Stages, each resumable, outputs in eval/qset2/:

  sample    stratified page sample (+ variant targets, comparison pairs, identifier tokens)     -> pages.jsonl
  generate  one question per sampled item with a local LLM (generator model)                   -> generated.jsonl
  filter    grounding (evidence quote must be in the page), lexical-leak and near-duplicate
            filters, then down-sample to the quotas                                            -> candidates.jsonl
  pool      top-10 pages from 4 diverse systems (BM25, nomic vector, bge-m3 vector, SERVER)    -> pool.jsonl
  judge     graded relevance 0/1/2 of every pooled page + the source page (judge model,
            a different family from the generator)                                             -> judged.jsonl
  finalize  drop questions whose source page is not judged relevant, unanswerable ones with a
            relevant page; split dev/test; write questions.jsonl, judgments.json, review.md

Gold is never chosen from a ranking: strict gold = the page the question was written from (identifier questions: every page
literally containing the token). Pooled judgments only feed the lenient score, as in the first set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sqlite3
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from docsearch.embed import EmbedServer, hf_file

H = Path(__file__).resolve().parents[1]
OUT = H / "eval" / "qset2"
DB = H / "data" / "current.db"
SEED = 20261031

GEN_MODEL = hf_file("unsloth/Qwen3.8-27B-GGUF", "Qwen3.8-27B-UD-Q4_K_M.gguf")
JUDGE_MODEL = hf_file("unsloth/gemma-4-26B-A4B-it-GGUF", "gemma-4-26B-A4B-it-UD-Q4_K_XL.gguf")

AZ = ("azure-docs", "azure-aks-docs", "azure-monitor-docs", "azure-compute-docs")
# 600 answerable = 60 identifier + 60 variant + 50 multi_page + 430 single-page (163 non-AZ repos, category chosen by the
# generator; 267 AZ by topic). Each stage samples OVERGEN x the quota so the filters can drop items.
REPO_QUOTA = {"azure-dev-docs": 45, "architecture-center": 35, "azure-docs-powershell": 35,
              "azure-rest-api-specs": 12, "finops-toolkit": 12, "azure-cli": 8, "sre-agent": 8, "azure-pipelines-tasks": 8}
AZ_CAT_QUOTA = {"howto": 120, "conceptual": 92, "troubleshooting": 55}
CAT_QUOTA = {"variant": 60, "multi_page": 50, "identifier": 60}
UNANS_QUOTA = {"absent_service": 20, "fake_feature": 20, "off_scope": 20}
OVERGEN = 1.4
TOPIC_CAT = {"troubleshooting": "troubleshooting", "troubleshooting-general": "troubleshooting", "troubleshooting-known-issue": "troubleshooting",
             "concept-article": "conceptual", "overview": "conceptual", "best-practice": "conceptual", "article": "conceptual",
             "how-to": "howto", "tutorial": "howto", "quickstart": "howto", "sample": "howto", "upgrade-and-migration-article": "howto"}
SKIP_TOPICS = {"generated-reference", "release-notes", "include", "toc"}
VARIANT_NAMES = {   # normalised variant value -> how a user would name it
    "azure-cli": "the Azure CLI", "cli": "the Azure CLI", "powershell": "Azure PowerShell", "azure-powershell": "Azure PowerShell",
    "azure-portal": "the Azure portal", "portal": "the Azure portal", "bicep": "Bicep", "arm": "an ARM template", "terraform": "Terraform",
    "python": "Python", "java": "Java", "javascript": "JavaScript", "csharp": "C#", "dotnet": ".NET", "go": "Go", "typescript": "TypeScript",
    "programming-language-csharp": "C#", "programming-language-python": "Python", "programming-language-java": "Java",
    "programming-language-javascript": "JavaScript", "programming-language-typescript": "TypeScript", "programming-language-powershell": "PowerShell",
    "platform-android": "Android", "platform-ios": "iOS", "platform-windows": "Windows", "platform-web": "a web app", "rest-api": "the REST API",
}
ABSENT_SERVICES = ["Azure Cosmos DB", "Azure Key Vault", "Azure SQL Database", "Azure SQL Managed Instance", "Azure Databricks", "Microsoft Purview",
                   "Microsoft Sentinel", "Microsoft Defender for Cloud", "Microsoft Intune", "Power BI", "Azure OpenAI in Foundry Models",
                   "Azure AI Search", "Azure Machine Learning", "Azure Database for MySQL", "Azure Virtual Desktop", "Azure DevOps Boards"]


JUNK_TOKEN = re.compile(r"ParameterSet|ViaIdentity|ByInputObject|Expanded$|ViaJson|^(Get|Set|New|Update|Remove|List|Create|Delete)"
                        r"(?=[A-Z])(?!-)|^Az[A-Z]")      # PowerShell parameter-set names and verb-less cmdlet fragments


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def rd(name):
    p = OUT / name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


def wr(name, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def connect():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, check_same_thread=False)


def page_text(db, doc_id, max_tokens=7000):
    parts, tok = [], 0
    for hp, text, n in db.execute("SELECT heading_path, text, token_count FROM chunks WHERE doc_id=? ORDER BY rid", (doc_id,)):
        if tok + n > max_tokens:
            parts.append("[... page truncated ...]"); break
        parts.append((f"## {hp}\n" if hp else "") + text); tok += n
    return "\n\n".join(parts)


def words(s):
    return re.findall(r"[a-z0-9]+", s.lower())


# ------------------------------------------------------------------------------------------------------------- sample
def sample(a):
    rng = random.Random(SEED); db = connect()
    docs = db.execute("SELECT d.doc_id, d.repo, d.path, d.title, d.ms_service, d.ms_topic, d.flags, sum(c.token_count), count(c.rid) "
                      "FROM docs d JOIN chunks c USING(doc_id) GROUP BY d.doc_id").fetchall()
    old = {g for q in (json.loads(l) for l in (H / "eval/questions.jsonl").read_text().splitlines()) for g in q["gold"]}
    ok = [d for d in docs if d[3] and (d[5] or "") not in SKIP_TOPICS and d[7] >= 250 and "include_unresolved" not in (d[6] or "")
          and f"{d[1]}/{d[2]}" not in old and "/.github/" not in f"/{d[2]}" and not d[2].lower().startswith(("readme", "changelog", "contributing"))
          and not re.search(r"support and help options|^index$", d[3], re.I)]
    group = lambda d: "AZ" if d[1] in AZ else d[1]
    cat_of = lambda d: TOPIC_CAT.get(d[5] or "", "howto" if d[1] not in AZ else None)
    used, items = set(), []

    def take(pool, n, cat, grp):
        rng.shuffle(pool); got = 0
        for d in pool:
            if got >= n: break
            if d[0] in used: continue
            used.add(d[0]); got += 1
            items.append({"kind": "page", "category": cat, "group": grp, "doc_id": d[0], "source": f"{d[1]}/{d[2]}", "title": d[3],
                          "service": d[4], "topic": d[5]})
        return got

    # variant targets (AZ + dev-docs): page with tab/pivot chunks, the variant value to ask for
    vrows = db.execute("SELECT doc_id, coalesce(variant_pivot, variant_tab) FROM chunks WHERE variant_pivot IS NOT NULL OR variant_tab IS NOT NULL").fetchall()
    vmap = defaultdict(Counter)
    for doc, vs in vrows:
        for v in vs.split(","):
            if v in VARIANT_NAMES: vmap[doc][v] += 1
    vdocs = [d for d in ok if d[0] in vmap and len(vmap[d[0]]) >= 2 and (d[1] in AZ or d[1] == "azure-dev-docs")]
    rng.shuffle(vdocs); nv = 0
    for d in vdocs:
        if nv >= round(CAT_QUOTA["variant"] * OVERGEN): break
        v = rng.choice(sorted(vmap[d[0]]))
        used.add(d[0]); nv += 1
        items.append({"kind": "page", "category": "variant", "group": group(d), "doc_id": d[0], "source": f"{d[1]}/{d[2]}", "title": d[3],
                      "service": d[4], "topic": d[5], "variant": v, "variant_name": VARIANT_NAMES[v], "other_variants": sorted(set(vmap[d[0]]) - {v})})

    # comparison pairs: two concept/overview pages of the same AZ service
    concept = defaultdict(list)
    for d in ok:
        if d[1] in AZ and d[4] and (d[5] in ("concept-article", "overview")) and d[0] not in used: concept[d[4]].append(d)
    svcs = [s for s, v in concept.items() if len(v) >= 2]; rng.shuffle(svcs); npair = 0
    for s in svcs * 3:
        if npair >= round(CAT_QUOTA["multi_page"] * OVERGEN): break
        cand = [d for d in concept[s] if d[0] not in used]
        if len(cand) < 2: continue
        x, y = rng.sample(cand, 2); used.update((x[0], y[0])); npair += 1
        items.append({"kind": "pair", "category": "multi_page", "group": "AZ", "doc_id": x[0], "doc_id2": y[0], "source": f"{x[1]}/{x[2]}",
                      "source2": f"{y[1]}/{y[2]}", "title": x[3], "title2": y[3], "service": s})

    # page-based: non-AZ repos by quota (category from topic, default howto/conceptual by content), AZ by service (sqrt allocation)
    for grp, q in REPO_QUOTA.items():
        pool = [d for d in ok if d[1] == grp and d[0] not in used]
        n = take(pool, round(q * OVERGEN), "howto", grp)
        for it in items[-n:]: it["category"] = "auto"           # generator picks howto / conceptual / troubleshooting
    for cat, quota in AZ_CAT_QUOTA.items():
        pool = [d for d in ok if d[1] in AZ and cat_of(d) == cat and d[0] not in used]
        by_svc = defaultdict(list)
        for d in pool: by_svc[d[4] or "?"].append(d)
        weights = {s: math.sqrt(len(v)) for s, v in by_svc.items()}; tot = sum(weights.values())
        want = round(quota * OVERGEN)
        alloc = {s: max(1, round(want * w / tot)) for s, w in weights.items()}
        for s in sorted(alloc, key=lambda s: -alloc[s]):
            take(by_svc[s], alloc[s], cat, "AZ")

    # identifier tokens: literal, rare (1-8 pages), from random chunks of eligible pages
    pat = re.compile(r"(?<![-\w.])(AADSTS\d{5,6}|[A-Z][a-z]+(?:[A-Z][a-z0-9]+){2,}|[a-z]+(?:_[a-z0-9]+){2,}|--[a-z]+(?:-[a-z]+)+|"
                     r"Microsoft\.[A-Z][A-Za-z]+/[a-zA-Z]+|(?:Get|Set|New|Remove|Update|Add|Enable|Disable)-Az[A-Z][A-Za-z]+)\b")
    seen_tok, nid = set(), 0
    ident_share = {"AZ": 0.6, "azure-docs-powershell": 0.25, "other": 0.15}     # cmdlet pages would otherwise dominate
    gid = lambda d: "AZ" if d[1] in AZ else d[1] if d[1] == "azure-docs-powershell" else "other"
    want_id = {g: round(CAT_QUOTA["identifier"] * OVERGEN * s) for g, s in ident_share.items()}; got_id = Counter()
    eligible = [d for d in ok if d[1] in AZ or d[1] in ("azure-dev-docs", "azure-docs-powershell", "azure-cli") and d[0] not in used]
    rng.shuffle(eligible)
    for d in eligible:
        doc = d[0]
        if got_id[gid(d)] >= want_id[gid(d)]:
            if all(got_id[g] >= want_id[g] for g in want_id): break
            continue
        text = page_text(db, doc, 4000); toks = [t for t in pat.findall(text) if t not in seen_tok and len(t) >= 8 and not JUNK_TOKEN.search(t)]
        if not toks: continue
        tok = rng.choice(toks); seen_tok.add(tok)
        pages = {r[0] for r in db.execute("SELECT DISTINCT d.repo || '/' || d.path FROM chunks c JOIN docs d USING(doc_id) "
                                          "WHERE instr(c.text, ?) > 0", (tok,))}
        if not 1 <= len(pages) <= 8: continue
        src = db.execute("SELECT repo || '/' || path, title FROM docs WHERE doc_id=?", (doc,)).fetchone()
        nid += 1; got_id[gid(d)] += 1
        items.append({"kind": "page", "category": "identifier", "group": "ident", "doc_id": doc, "source": src[0], "title": src[1],
                      "token": tok, "gold": sorted(pages)})
        if nid % 10 == 0: log(f"identifier tokens: {nid}")

    # unanswerable seeds
    rng2 = random.Random(SEED + 1)
    real_svcs = [s for s, _ in Counter(d[4] for d in ok if d[1] in AZ and d[4]).most_common(80)]
    for kind, n in UNANS_QUOTA.items():
        for i in range(round(n * OVERGEN)):
            seed = {"absent_service": lambda: rng2.choice(ABSENT_SERVICES), "fake_feature": lambda: rng2.choice(real_svcs),
                    "off_scope": lambda: rng2.choice(["AWS", "Google Cloud", "on-premises Kubernetes", "Linux administration",
                                                       "Microsoft 365 / Office", "general programming", "networking hardware", "Oracle Cloud"])}[kind]()
            items.append({"kind": "unanswerable", "category": "unanswerable", "group": "unans", "unans_kind": kind, "seed": seed})

    for i, it in enumerate(items): it["item"] = f"s{i:04d}"
    wr("pages.jsonl", items)
    log("sampled", Counter(i["category"] for i in items), Counter(i["group"] for i in items))


# ----------------------------------------------------------------------------------------------------------- LLM glue
class LlmServer(EmbedServer):
    def __init__(self, model, port, parallel, ctx, device="ROCm0"):
        super().__init__(model, device, port, ctx=ctx, parallel=parallel)

    def _cmd(self, exe):
        return [exe, "-m", str(self.model), "--device", self.device, "-ngl", "99", "-c", str(self.ctx), "-np", str(self.parallel),
                "--port", str(self.port), "--host", "127.0.0.1", "--jinja", "-fa", "on", "--reasoning-budget", "0", "--cache-reuse", "256"]

    def __enter__(self):
        if self._up(): raise RuntimeError(f"port {self.port} already answers: refusing to reuse an unknown server")
        return super().__enter__()


def chat(http, url, prompt, schema, max_tokens=400, temperature=0.7, seed=0):
    body = {"messages": [{"role": "user", "content": prompt}], "temperature": temperature, "max_tokens": max_tokens, "seed": seed,
            "response_format": {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}}
    for attempt in range(3):
        try:
            r = http.post(url + "/v1/chat/completions", json=body, timeout=600); r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as e:
            err = e; time.sleep(2)
    return {"error": str(err)}


def run_parallel(todo, fn, out_name, workers):
    done = {r["item"] for r in rd(out_name)}; todo = [t for t in todo if t["item"] not in done]
    log(f"{len(done)} done, {len(todo)} to do")
    lock = threading.Lock(); f = (OUT / out_name).open("a"); t0 = time.time(); n = 0
    def one(t):
        nonlocal n
        r = fn(t)
        with lock:
            f.write(json.dumps(r, ensure_ascii=False) + "\n"); f.flush(); n += 1
            if n % 25 == 0: log(f"{n}/{len(todo)}  {n / (time.time() - t0):.2f}/s")
    with ThreadPoolExecutor(workers) as ex: list(ex.map(one, todo))
    f.close()


# ----------------------------------------------------------------------------------------------------------- generate
STYLE = [("a short search-box query of 4-9 words, not necessarily a full sentence", 0.3),
         ("a natural one-sentence question", 0.45),
         ("a question that first states the user's situation or symptom in one clause, then asks", 0.25)]
COMMON = ("Rules: write as an Azure practitioner who has NOT read this page and has a real goal. Do not copy wording from the page: "
          "never reuse a run of 4 or more consecutive words from it, except unavoidable product, feature, role or command names. "
          "Never mention 'this page', 'the article' or 'the documentation'. Avoid trivia; ask what someone would actually need. "
          "The answer must be clearly contained in the page. 'evidence' = a short verbatim quote (max 40 words) copied exactly "
          "from the page that answers it. If the page cannot support such a question, set skip=true.")
GEN_SCHEMA = {"type": "object", "properties": {"skip": {"type": "boolean"}, "question": {"type": "string"}, "evidence": {"type": "string"},
              "category": {"type": "string", "enum": ["howto", "conceptual", "troubleshooting"]}}, "required": ["skip", "question", "evidence"]}
UNANS_SCHEMA = {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]}
CAT_TASK = {
    "howto": "Write a question asking HOW to accomplish a concrete task that the page explains.",
    "conceptual": "Write a question about understanding a concept, a design choice, a limit or a behaviour that the page explains (why / what / when / which).",
    "troubleshooting": "Write a question from someone facing a problem, error or unexpected behaviour that the page helps resolve.",
    "auto": "Write the kind of question (how-to task, concept, or troubleshooting) this page answers best, and report it in 'category'.",
    "identifier": "The question MUST contain the exact identifier `{token}` (as a user who saw it in an error, a template, a command or a log), "
                  "and ask what it means or how to use or fix it. If the identifier is only a placeholder, a sample resource "
                  "name, or an internal name nobody would search for, set skip=true.",
    "variant": "The page shows the same task for several tools or languages ({others}). Write a how-to question that explicitly asks "
               "to do it with {variant_name}, for a task the page shows for {variant_name}.",
}


def gen_prompt(db, it, rng):
    style = rng.choices([s for s, _ in STYLE], [w for _, w in STYLE])[0]
    if it["kind"] == "unanswerable":
        k, s = it["unans_kind"], it["seed"]
        task = {"absent_service": f"Write a realistic, specific technical question about {s} (its own features, configuration or behaviour, "
                                  f"not generic Azure). Not about PowerShell cmdlet syntax or REST API parameters.",
                "fake_feature": f"Write a realistic-sounding question about a capability of the Azure service '{s}' that does NOT exist "
                                f"(a plausible but invented setting, option or integration). It must sound like a genuine user question.",
                "off_scope": f"Write a realistic technical question about {s} that has nothing to do with Microsoft Azure."}[k]
        return f"{task}\nWrite it as {style}. Output JSON with 'question'.", UNANS_SCHEMA, style
    if it["kind"] == "pair":
        a, b = page_text(db, it["doc_id"], 3200), page_text(db, it["doc_id2"], 3200)
        task = ("Two pages are given. Write ONE question whose good answer needs information from BOTH pages (a comparison, a choice "
                "between them, or how they work together). If the pages are unrelated so no natural question exists, set skip=true. "
                "'evidence' = a verbatim quote from page A.")
        return (f"{task}\nWrite it as {style}.\n{COMMON}\n\n=== PAGE A: {it['title']}\n{a}\n\n=== PAGE B: {it['title2']}\n{b}", GEN_SCHEMA, style)
    task = CAT_TASK[it["category"]].format(token=it.get("token"), variant_name=it.get("variant_name"),
                                           others=", ".join(VARIANT_NAMES.get(v, v) for v in it.get("other_variants", []) + [it.get("variant", "")]))
    if it["category"] == "identifier": style = STYLE[1][0]
    return f"{task}\nWrite it as {style}.\n{COMMON}\n\n=== PAGE: {it['title']}\n{page_text(db, it['doc_id'])}", GEN_SCHEMA, style


def generate(a):
    items = rd("pages.jsonl"); db = connect()
    with LlmServer(GEN_MODEL, 8094, a.parallel, a.parallel * 12288, a.device) as srv:
        http = httpx.Client()
        def fn(it):
            rng = random.Random(f"{SEED}-{it['item']}")
            prompt, schema, style = gen_prompt(db, it, rng)
            out = chat(http, srv.url, prompt, schema, seed=int(hashlib.md5(it["item"].encode()).hexdigest()[:6], 16))
            return {**it, "style": style, "gen": out}
        run_parallel(items if not a.limit else items[:a.limit], fn, "generated.jsonl", a.parallel)


# ------------------------------------------------------------------------------------------------------------- filter
def norm(s):
    return " ".join(re.sub(r"[*_`#>|\[\]()]", " ", s.lower()).split())


def grams(ws, n):
    return {tuple(ws[i:i + n]) for i in range(len(ws) - n + 1)}


LEAK_N = 6           # a question sharing any 6-word run with its source page is a copy, not a paraphrase


def filter_(a):
    db = connect(); rng = random.Random(SEED); stats = Counter(); keep = []
    for r in rd("generated.jsonl"):
        g = r.get("gen", {})
        if "error" in g: stats["llm_error"] += 1; continue
        q = (g.get("question") or "").strip()
        if r["kind"] != "unanswerable":
            if g.get("skip") or not q: stats["skipped_by_llm"] += 1; continue
            text = page_text(db, r["doc_id"], 10**6) + ("\n" + page_text(db, r["doc_id2"], 10**6) if r["kind"] == "pair" else "")
            ev, nt = norm(g.get("evidence", "")), norm(text)
            ev_ws = words(ev)
            grounded = len(ev_ws) >= 3 and (ev in nt or len(grams(ev_ws, 3) & grams(words(nt), 3)) >= 0.85 * len(grams(ev_ws, 3)))
            if not grounded: stats["ungrounded"] += 1; continue
            qw = words(q.replace(r.get("token") or "\0", " "))
            if grams(qw, LEAK_N) & grams(words(text), LEAK_N): stats["lexical_leak"] += 1; continue
            if r["category"] == "identifier" and r["token"] not in q: stats["token_missing"] += 1; continue
            if r["category"] == "variant" and not re.search(re.escape(r["variant_name"].replace("the ", "").replace("an ", "")), q, re.I):
                stats["variant_missing"] += 1; continue
            cat = g.get("category") if r["category"] == "auto" and g.get("category") else r["category"]
        else:
            if not q: stats["empty"] += 1; continue
            cat = "unanswerable"
        keep.append({**r, "question": q, "cat": cat})
    # near-duplicates (word-set Jaccard >= .7)
    out, sets = [], []
    for r in keep:
        s = set(words(r["question"]))
        if any(len(s & o) / len(s | o) >= 0.7 for o in sets): stats["near_duplicate"] += 1; continue
        out.append(r); sets.append(s)
    # down-sample to quota x 1.08 (finalize trims to the exact quota after judging)
    buf = 1.08; final = []
    groups = defaultdict(list)
    for r in out:
        key = (r["category"] if r["category"] in ("variant", "multi_page", "identifier", "unanswerable")
               else f"AZ:{r['category']}" if r["group"] == "AZ" else f"repo:{r['group']}")
        groups[key].append(r)
    quota = {**{k: v for k, v in CAT_QUOTA.items()}, **{f"AZ:{k}": v for k, v in AZ_CAT_QUOTA.items()},
             **{f"repo:{k}": v for k, v in REPO_QUOTA.items()}, "unanswerable": sum(UNANS_QUOTA.values()) * OVERGEN}
    for k, rs in sorted(groups.items()):
        rng.shuffle(rs); n = math.ceil(quota[k] * buf); final += rs[:n]
        stats[f"short:{k}"] += max(0, math.ceil(quota[k]) - len(rs))
    wr("candidates.jsonl", final)
    log("filter:", dict(stats)); log("candidates:", Counter(r["cat"] for r in final), len(final))


# --------------------------------------------------------------------------------------------------------------- pool
def all_questions():
    """Candidates + the 58 v1 questions (re-judged with the same judge, so dev numbers use the same rules)."""
    qs = [{"item": r["item"], "question": r["question"], "expected_variant": r.get("variant")} for r in rd("candidates.jsonl")]
    for l in (H / "eval/questions.jsonl").read_text().splitlines():
        q = json.loads(l); qs.append({"item": "v1:" + q["id"], "question": q["question"], "expected_variant": q.get("expected_variant")})
    return qs


def pool(a):
    from dataclasses import replace
    import numpy as np
    from docsearch import evalrun as E
    from docsearch.config import load_config
    from docsearch.embed import Embedder
    from docsearch.expand import ExpandServer, QueryExpander
    from docsearch.rerank import Reranker, RerankServer
    from docsearch.search import SearchConfig
    from docsearch.server import SERVER_CONFIG, _Embeddings
    qs = all_questions(); cfg = load_config(H / "repos.toml"); D = SearchConfig()

    class Bge(EmbedServer):
        def __init__(s): super().__init__(hf_file("ggml-org/bge-m3-Q8_0-GGUF", "bge-m3-q8_0.gguf"), "ROCm0", 8095, ctx=4096, parallel=2)
        def _cmd(s, exe):
            c = super()._cmd(exe); c[c.index("--pooling") + 1] = "cls"; c[c.index("-b") + 1] = "4096"; c[c.index("-ub") + 1] = "4096"; return c

    texts = [q["question"] for q in qs]
    with ExpandServer() as xs:
        ex = QueryExpander(xs.url, OUT / "expansions.json")
        for i, t in enumerate(texts):
            ex(t)
            if i % 100 == 0: log(f"expanded {i}/{len(texts)}")
    nomic = _Embeddings(); memo_n = {}
    for t in {s for q in texts for s in (q, q + " " + ex.cache[q])}: memo_n[t] = nomic(t)
    with Bge() as bs:
        e = Embedder(bs.url, workers=1); memo_b = {t: e.embed([t], "")[0] for t in texts}
    np.save(OUT / "qvec_nomic.npy", np.array([np.frombuffer(memo_n[t], dtype=np.float32) for t in texts]))
    log("embedded queries")
    bge_db = H / "data" / "exp-bge-m3.db"
    with RerankServer("bge-v2-m3-q8") as rs:
        rr = Reranker(rs.url, "bge-v2-m3-q8", cache=OUT / "rerank_cache.jsonl")
        systems = {
            "bm25": E.DocsearchSystem(DB, memo_n.__getitem__, cfg, replace(D, vector=0), "bm25", measure=False),
            "nomic-vec": E.DocsearchSystem(DB, memo_n.__getitem__, cfg, replace(D, bm25=0, phrase=0, ident=0), "nomic-vec", measure=False),
            "bge-vec": E.DocsearchSystem(bge_db, memo_b.__getitem__, cfg, replace(D, bm25=0, phrase=0, ident=0), "bge-vec", measure=False),
            "server": E.DocsearchSystem(DB, memo_n.__getitem__, cfg, replace(SERVER_CONFIG, expand_vec=1.0), "server", measure=False,
                                        reranker=lambda q, d: rr.score(q, d), expander=lambda q: ex.cache[q]),
        }
        rows = []
        for i, q in enumerate(qs):
            pages = defaultdict(list)
            for name, s in systems.items():
                for rank, src in enumerate(s.run(q)["ranked"][:10], 1): pages[src].append([name, rank])
            rows.append({**q, "pages": pages})
            if i % 100 == 0: log(f"pooled {i}/{len(qs)}")
    wr("pool.jsonl", rows)
    log("pool sizes: mean", round(sum(len(r["pages"]) for r in rows) / len(rows), 1))


# -------------------------------------------------------------------------------------------------------------- judge
JUDGE_SCHEMA = {"type": "object", "properties": {"reason": {"type": "string"}, "grade": {"type": "integer", "enum": [0, 1, 2]}},
                "required": ["reason", "grade"]}
JUDGE_PROMPT = """You grade results of a search engine over Microsoft Azure documentation.

Question: {q}

Candidate page: {title}
Source: {source}
Description: {desc}
Outline: {outline}

Excerpts (the parts of the page closest to the question):
{excerpts}

Grade the page:
2 = the page answers the question: a user asking it would be satisfied by this page (possibly after reading it in full).
1 = on the right topic and partly useful, but it does not answer the main point of the question.
0 = not useful for this question.
If the question asks for a specific tool, language or platform (for example "with PowerShell", "in Java"), grade 2 only if the page covers it for that tool, language or platform.
Judge only from what is shown. Give a one-sentence reason first, then the grade, as JSON."""


def excerpt_builder():
    import numpy as np
    from docsearch import store
    db = store.connect(DB, readonly=True, shared=True); lock = threading.Lock()
    def build(source, qvec, question):
        repo, path = source.split("/", 1)
        with lock:
            d = db.execute("SELECT doc_id, title, description FROM docs WHERE repo=? AND path=?", (repo, path)).fetchone()
            if not d: return None
            ch = db.execute("SELECT c.rid, c.heading_path, c.text, v.embedding FROM chunks c LEFT JOIN chunks_vec v ON v.rowid=c.rid "
                            "WHERE c.doc_id=? ORDER BY c.rid", (d[0],)).fetchall()
        heads = list(dict.fromkeys(h for _, h, _, _ in ch if h))
        cos = [float(np.frombuffer(e, dtype=np.float32) @ qvec) if e else -1 for *_, e in ch]
        qw = set(words(question))
        lex = [len(qw & set(words(t))) for _, _, t, _ in ch]
        pick = list(dict.fromkeys([0] + sorted(range(len(ch)), key=lambda i: -cos[i])[:2] + [max(range(len(ch)), key=lambda i: lex[i])]))
        ex = "\n\n".join(f"[{ch[i][1] or 'top of page'}]\n{ch[i][2][:1600]}" for i in sorted(pick))
        return {"title": d[1], "desc": (d[2] or "")[:300], "outline": " | ".join(heads[:40])[:1500], "excerpts": ex}
    return build


def judge(a):
    import numpy as np
    pool_rows = rd("pool.jsonl"); qv = np.load(OUT / "qvec_nomic.npy")
    cands = {r["item"]: r for r in rd("candidates.jsonl")}
    todo = []
    for i, r in enumerate(pool_rows):
        c = cands.get(r["item"], {})
        srcs = list(r["pages"]) + [s for s in (c.get("source"), c.get("source2")) if s and c.get("category") != "identifier"]
        for s in dict.fromkeys(srcs):
            todo.append({"item": f"{r['item']}|{s}", "qi": i, "question": r["question"], "source": s})
    if a.limit: todo = todo[:a.limit]
    build = excerpt_builder()
    with LlmServer(JUDGE_MODEL, 8093, a.parallel, a.parallel * 5120, a.device) as srv:
        http = httpx.Client()
        def fn(t):
            x = build(t["source"], qv[t["qi"]], t["question"])
            if x is None: return {**t, "grade": None, "reason": "page not in index"}
            out = chat(http, srv.url, JUDGE_PROMPT.format(q=t["question"], source=t["source"], **x), JUDGE_SCHEMA, max_tokens=200, temperature=0)
            return {"item": t["item"], "question": t["question"], "source": t["source"], **out}
        run_parallel(todo, fn, "judged.jsonl", a.parallel)


# ----------------------------------------------------------------------------------------------------------- finalize
def finalize(a):
    rng = random.Random(SEED); db = connect()
    grades = defaultdict(dict); reasons = {}
    for r in rd("judged.jsonl"):
        it, src = r["item"].split("|", 1)
        if r.get("grade") is not None: grades[it][src] = r["grade"]; reasons[r["item"]] = r.get("reason", "")
    url = dict(((f"{r[0]}/{r[1]}"), r[2]) for r in db.execute("SELECT repo, path, url FROM docs"))
    stats, kept = Counter(), defaultdict(list)
    for c in rd("candidates.jsonl"):
        g = grades.get(c["item"])
        if g is None: stats["not_judged"] += 1; continue
        if c["category"] == "unanswerable":
            if any(v == 2 for v in g.values()): stats["unans_answerable"] += 1; continue
        elif c["category"] == "identifier":
            pass                                            # gold = literal occurrence; judgments only add lenient pages
        elif c["category"] == "multi_page":
            if min(g.get(c["source"], 0), g.get(c["source2"], 0)) < 1: stats["pair_source_irrelevant"] += 1; continue
        elif g.get(c["source"], 0) < 2:
            stats[f"source_not_2:{c['cat']}"] += 1; continue
        key = (c["category"] if c["category"] in ("variant", "multi_page", "identifier", "unanswerable")
               else f"AZ:{c['category']}" if c["group"] == "AZ" else f"repo:{c['group']}")
        kept[key].append(c)
    quota = {**CAT_QUOTA, **{f"AZ:{k}": v for k, v in AZ_CAT_QUOTA.items()}, **{f"repo:{k}": v for k, v in REPO_QUOTA.items()},
             "unanswerable": sum(UNANS_QUOTA.values())}
    final = []
    for k in sorted(kept):
        rs = kept[k]; rng.shuffle(rs); final += rs[:quota[k]]
        if len(rs) < quota[k]: stats[f"short:{k}"] = quota[k] - len(rs)
    # dev/test split, stratified by final category
    bycat = defaultdict(list)
    for c in final: bycat[c["cat"]].append(c)
    qs, judg = [], {"_about": "qset2 pooled judgments (judge: gemma-4-26B-A4B, grade 2 = answers). also_ok = grade-2 pages beyond the gold. "
                              "grades holds every judged page (0/1/2) for graded metrics."}
    n = 0
    for cat in sorted(bycat):
        rs = sorted(bycat[cat], key=lambda c: c["item"]); rng.shuffle(rs)
        for i, c in enumerate(rs):
            n += 1; qid = f"n{n:04d}"
            gold = [] if cat == "unanswerable" else c.get("gold") or [c["source"]] + ([c["source2"]] if c.get("source2") else [])
            q = {"id": qid, "category": cat, "origin": "llm:qwen3.8-27b", "question": c["question"], "gold": gold,
                 "answerable": cat != "unanswerable", "split": "test" if i % 2 else "dev", "item": c["item"], "style": c["style"]}
            if c.get("variant"): q["expected_variant"] = c["variant"]
            if c.get("token"): q["token"] = c["token"]
            if c.get("unans_kind"): q["unans_kind"] = c["unans_kind"]
            qs.append(q)
            g = grades[c["item"]]
            judg[qid] = {"also_ok": sorted(s for s, v in g.items() if v == 2 and s not in gold), "grades": g}
    v1 = {"_about": "v1 questions re-judged by the qset2 judge (same rules). Compare with eval/judgments.json."}
    for it, g in grades.items():
        if it.startswith("v1:"): v1[it[3:]] = {"also_ok": sorted(s for s, v in g.items() if v == 2), "grades": g}
    wr("questions.jsonl", qs)
    (OUT / "judgments.json").write_text(json.dumps(judg, indent=1, ensure_ascii=False))
    (OUT / "judgments_v1.json").write_text(json.dumps(v1, indent=1, ensure_ascii=False))
    log("finalize:", dict(stats)); log("final:", Counter(q["category"] for q in qs), Counter(q["split"] for q in qs), len(qs))
    review(qs, grades, reasons, url)


def review(qs, grades, reasons, url):
    """review.md: 25 questions + 25 judgments, random and stratified, for a human to mark."""
    rng = random.Random(SEED + 7)
    link = lambda s: f"[{s}]({url[s]})" if url.get(s) else f"`{s}`"
    byc = defaultdict(list)
    for q in qs: byc[q["category"]].append(q)
    pick_q = []
    while len(pick_q) < 25:
        for c in sorted(byc):
            rest = [q for q in byc[c] if q not in pick_q]
            if rest and len(pick_q) < 25: pick_q.append(rng.choice(rest))
    jud = [(q, s, g) for q in qs for s, g in grades[q["item"]].items() if s not in q["gold"]]
    pick_j = []
    for g, n in ((2, 10), (1, 7), (0, 8)):
        pool = [x for x in jud if x[2] == g]; pick_j += rng.sample(pool, min(n, len(pool)))
    rng.shuffle(pick_j)
    L = ["# qset2 human review", "",
         "Mark each item by replacing `[ ]` with `[x]` on the line that applies. Add a note after `note:` if useful.", "",
         "## A. Questions (25)", "For each: is it a realistic question, and does the gold page answer it?", ""]
    for i, q in enumerate(pick_q, 1):
        L += [f"### A{i}. {q['id']} ({q['category']})", f"> {q['question']}", ""]
        L += [f"gold: {', '.join(link(s) for s in q['gold'])}" if q["gold"] else "gold: none (should be UNANSWERABLE from this corpus)"]
        if q.get("expected_variant"): L += [f"expected variant: `{q['expected_variant']}`"]
        L += ["", "- [ ] realistic and gold correct", "- [ ] realistic but gold wrong/incomplete", "- [ ] unrealistic / badly phrased",
              "- note:", ""]
    L += ["## B. Judge decisions (25)", "The judge graded these pooled pages (2 = answers, 1 = partial, 0 = not useful). Do you agree?", ""]
    for i, (q, s, g) in enumerate(pick_j, 1):
        L += [f"### B{i}. {q['id']} → grade **{g}**", f"> {q['question']}", "", f"page: {link(s)}",
              f"judge: _{reasons.get(q['item'] + '|' + s, '')}_", "", "- [ ] agree", "- [ ] should be 2", "- [ ] should be 1",
              "- [ ] should be 0", "- note:", ""]
    (OUT / "review.md").write_text("\n".join(L))
    log("wrote", OUT / "review.md")


def main():
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    g = sub.add_parser("generate"); g.add_argument("--parallel", type=int, default=4); g.add_argument("--device", default="ROCm0")
    g.add_argument("--limit", type=int)
    sub.add_parser("filter"); sub.add_parser("pool"); sub.add_parser("finalize")
    j = sub.add_parser("judge"); j.add_argument("--parallel", type=int, default=8); j.add_argument("--device", default="ROCm0")
    j.add_argument("--limit", type=int)
    a = ap.parse_args()
    {"sample": sample, "generate": generate, "filter": filter_, "pool": pool, "judge": judge, "finalize": finalize}[a.cmd](a)


if __name__ == "__main__":
    main()
