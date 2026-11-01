"""qinc: questions whose answer lives only in a reconstructed include (see eval/README.md, 'qinc').

  uv run python eval/qinc_build.py <unres.json> <questions_dir> [<more questions_dirs>...]
(each topic's q_<topic>.jsonl is looked up in the dirs in order)

Gold of a question = every page that uses the include (their rendered text contains the answer). Before the heal those pages
did not contain it in the index, so pre-heal vs post-heal measures the coverage gain. Split: topic-stratified, 3 dev / 3 test
questions per topic (by position in the file), so `--split test` stays a fair holdout for later tuning.
"""
import json, sys
from pathlib import Path

H = Path(__file__).resolve().parents[1]; OUT = H / "eval" / "qinc"
TOPICS = {  # topic -> (include paths whose users are gold, label)
    "t0": (["~/reusable-content/ce-skilling/azure/includes/quickstarts-free-trial-note.md"], "free-trial-note"),
    "t1": (["~/reusable-content/ce-skilling/azure/includes/updated-for-az.md"], "az-powershell-note"),
    "t2": (["~/reusable-content/azure-cli/azure-cli-prepare-your-environment.md",
            "~/reusable-content/azure-cli/azure-cli-prepare-your-environment-no-header.md"], "cli-prepare-environment"),
    "t3": (["~/reusable-content/ce-skilling/azure/includes/aks/includes/preview/preview-callout.md"], "aks-preview-callout"),
    "t5": (["~/reusable-content/ce-skilling/azure/includes/resource-manager-quickstart-introduction.md"], "arm-template-intro"),
    "t7": (["~/reusable-content/ce-skilling/azure/includes/cloud-shell-try-it.md"], "cloud-shell-try-it"),
    "t8": (["~/reusable-content/ce-skilling/azure/includes/resource-manager-quickstart-bicep-introduction.md"], "bicep-intro"),
    "t9": (["~/azure-dev-docs-pr/articles/terraform/includes/terraform-init.md"], "terraform-init"),
    # terraform family, added after the first batch (ids of the first 48 questions stay unchanged)
    "t10": (["~/azure-dev-docs-pr/articles/terraform/includes/abstract.md"], "terraform-abstract"),
    "t11": (["~/azure-dev-docs-pr/articles/terraform/includes/terraform-plan.md",
             "~/azure-dev-docs-pr/articles/terraform/includes/terraform-plan-notes.md"], "terraform-plan"),
    "t12": (["~/azure-dev-docs-pr/articles/terraform/includes/terraform-apply-plan.md"], "terraform-apply-plan"),
    "t13": (["~/azure-dev-docs-pr/articles/terraform/includes/terraform-plan-destroy.md"], "terraform-plan-destroy"),
}

def main(unres, *qdirs):
    use = json.load(open(unres)); OUT.mkdir(exist_ok=True)
    qs, n = [], 0
    for t, (incs, label) in TOPICS.items():
        gold = sorted({f"{r}/{p}" for i in incs for r, p, _ in use.get(i, [])})
        qf = next(Path(d) / f"q_{t}.jsonl" for d in qdirs if (Path(d) / f"q_{t}.jsonl").exists())
        rows = [json.loads(l) for l in qf.read_text().splitlines() if l.strip()]
        for k, row in enumerate(rows):
            n += 1
            qs.append({"id": f"i{n:04d}", "category": "include", "origin": "llm:haiku-5.5", "question": row["question"].strip(),
                       "gold": gold, "answerable": True, "split": "dev" if k % 2 == 0 else "test", "topic": label, "style": row.get("style")})
    (OUT / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in qs))
    (OUT / "judgments.json").write_text(json.dumps({"_about": "qinc: gold = every page using the reconstructed include; no pooled extras"}))
    print(len(qs), "questions;", {l: len({f'{r}/{p}' for i in inc for r, p, _ in use.get(i, [])}) for _, (inc, l) in TOPICS.items()})

if __name__ == "__main__":
    main(*sys.argv[1:])
