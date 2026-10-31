Claude Code memory export (2026-10-31). Install on the new machine:
  d=~/.claude/projects/$(pwd | sed 's#/#-#g')/memory   # run from the project dir you launch claude in
  mkdir -p "$d" && cp MEMORY.md docsearch-project.md "$d"/
If the project path differs, edit paths mentioned in docsearch-project.md. Either way, tell the new Claude to read LLM/docsearch/HANDOFF.md ("Move to the new server" section) first.
