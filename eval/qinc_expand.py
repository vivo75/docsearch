"""Cache the Gemma query expansion of every qinc question (compare.py reads eval/qinc/expansions.json, never calls the LLM)."""
import json
from pathlib import Path
from docsearch.expand import ExpandServer, QueryExpander

OUT = Path(__file__).resolve().parent / "qinc"
texts = [json.loads(l)["question"] for l in (OUT / "questions.jsonl").read_text().splitlines()]
with ExpandServer() as xs:
    ex = QueryExpander(xs.url, OUT / "expansions.json")
    for t in texts: ex(t)
print(len(ex.cache), "expansions cached")
