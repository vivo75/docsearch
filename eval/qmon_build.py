"""qmon: questions whose answer lives in the Azure Monitor `horz-monitor-*` includes (private reusable-content repo, unresolved in the index).

  uv run python eval/qmon_build.py        -> eval/qmon/questions.jsonl + judgments.json
Passages (eval/qmon/passages/) are the generic include text taken from the rendered App Service monitoring page (service-specific text removed);
questions (eval/qmon/q/q_<topic>.jsonl, written by Sonnet 5.5, no 5-word copy from the passage) are generic. Gold = every page that uses the include
(eval/qmon/unresolved.json: include -> [repo, path] from IncludeResolver over the pages flagged include_unresolved). Split: 3 dev / 3 test per topic.
Same protocol as qinc (eval/qinc_build.py)."""
import json
from pathlib import Path

H = Path(__file__).resolve().parents[1]; OUT = H / "eval" / "qmon"
BASE = "~/reusable-content/ce-skilling/azure/includes/azure-monitor/horizontals/horz-monitor-"
TOPICS = ["resource-types", "data-storage", "platform-metrics", "resource-logs", "activity-log", "analyze-data", "external-tools",
          "kusto-queries", "alerts", "advisor-recommendations"]

def main():
    use = json.loads((OUT / "unresolved.json").read_text()); qs, n = [], 0
    for t in TOPICS:
        gold = sorted({f"{r}/{p}" for r, p, _ in use[f"{BASE}{t}.md"]})
        rows = [json.loads(l) for l in (OUT / "q" / f"q_{t}.jsonl").read_text().splitlines() if l.strip()]
        for k, row in enumerate(rows):
            n += 1
            qs.append({"id": f"m{n:04d}", "category": "include", "origin": "llm:sonnet-5.5", "question": row["question"].strip(), "gold": gold,
                       "answerable": True, "split": "dev" if k % 2 == 0 else "test", "topic": t, "style": row.get("style")})
    (OUT / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in qs))
    (OUT / "judgments.json").write_text(json.dumps({"_about": "qmon: gold = every page using the horz-monitor include; no pooled extras"}))
    print(len(qs), "questions;", {t: len({g for q in qs if q["topic"] == t for g in q["gold"]}) for t in TOPICS})

if __name__ == "__main__":
    main()
