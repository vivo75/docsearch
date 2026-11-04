# eval/examples: runnable one-off diagnostics

Each file is standalone (`uv run python eval/examples/<name>.py` from the project
root) and documents the case it was written for in its docstring.

- `rank_distance.py`: rank distance of candidate pages for one question
  (server config, live index). Written for the q013 judgment review.
