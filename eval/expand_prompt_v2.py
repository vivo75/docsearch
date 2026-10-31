import json, sys
from dataclasses import replace
from pathlib import Path
from docsearch import evalrun as E, expand as X
from docsearch.config import load_config
from docsearch.rerank import Reranker, RerankServer
from docsearch.server import _Embeddings, SERVER_CONFIG
H=Path("/home/vivo/repo/Microsoft/LLM/docsearch"); C2=H/"eval/results/expansions_v2.json"
X.PROMPT=("You help search Microsoft Azure documentation. Write the title of the Learn article that would best answer the question, "
          "then add keywords: the official Azure service and feature names, built-in role or setting names, and CLI/PowerShell/portal nouns "
          "the documentation uses instead of the user's everyday wording. Output one line, max 30 words, no explanation. Question: {q}")
strict,lenient=E.load_questions(),E.load_questions(lenient=True)
with X.ExpandServer() as srv:
    ex=X.QueryExpander(srv.url,C2)
    for q in strict: ex(q["question"])
for k in ("How do I give someone read-only access to a resource group?","How do I back up virtual machines in Azure and what gets backed up?"): print(k,"->",ex.cache[k])
cfg=load_config(H/"repos.toml"); emb=_Embeddings(); memo={}
embed=lambda q: memo.setdefault(q,emb(q)); base=replace(SERVER_CONFIG,expand_vec=1.0)
with RerankServer("bge-v2-m3-q8") as rs:
    rr=Reranker(rs.url,"bge-v2-m3-q8",cache=H/"eval/results/rerank_cache.jsonl")
    for qs,label in ((strict,"STRICT"),(lenient,"LENIENT")):
        for q in qs: embed(q["question"]+" "+ex.cache[q["question"]])
        print(f"== {label} ==\n{E.HEADER}")
        for name,c in (("v2 vec+rerank",base),("v2 vec",replace(base,rerank_top=0))):
            s=E.DocsearchSystem(H/"data/current.db",embed,cfg,c,name,measure=False,reranker=lambda q,d:rr.score(q,d),expander=lambda q:ex.cache[q])
            summ,_=E.run_system(s,qs); print(E.fmt_row(name,summ),flush=True)
