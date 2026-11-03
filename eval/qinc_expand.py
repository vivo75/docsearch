"""python eval/qinc_expand.py [qinc|qmon]: cache the Gemma query expansion of every question (compare.py reads eval/<set>/expansions.json, never calls the LLM)."""
import json, sys
from pathlib import Path
from docsearch.expand import ExpandServer, QueryExpander

OUT = Path(__file__).resolve().parent / (sys.argv[1] if len(sys.argv) > 1 else "qinc")
texts = [json.loads(l)["question"] for l in (OUT / "questions.jsonl").read_text().splitlines()]
with ExpandServer() as xs:
    ex = QueryExpander(xs.url, OUT / "expansions.json")
    for t in texts: ex(t)
print(len(ex.cache), "expansions cached")
