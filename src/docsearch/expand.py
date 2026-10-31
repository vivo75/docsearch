"""Query expansion with a small local LLM: rewrite a question into the terminology the documentation uses."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import httpx

from .embed import EmbedServer

GEMMA = Path("~/.lmstudio/models/lmstudio-community/gemma-4-E4B-it-GGUF/gemma-4-E4B-it-Q4_K_M.gguf").expanduser()
PROMPT = ("You help search Microsoft Azure documentation. Rewrite the user's question as a short list of search keywords and phrases "
          "using the exact terminology Azure documentation uses (role names, feature names, CLI/PowerShell nouns, synonyms). "
          "Output only one line of space-separated keywords, max 25 words. Question: {q}")


class ExpandServer(EmbedServer):
    def __init__(self, device: str = "Vulkan0", port: int = 8096):
        super().__init__(GEMMA, device, port, ctx=8192, parallel=2)

    def _cmd(self, exe: str) -> list[str]:
        return [exe, "-m", str(self.model), "--device", self.device, "-ngl", "99", "-c", str(self.ctx), "-np", str(self.parallel),
                "--port", str(self.port), "--host", "127.0.0.1", "--jinja", "-fa", "on", "--reasoning-budget", "0"]


class QueryExpander:
    def __init__(self, url: str, cache: Path | None = None):
        self.url, self.http = url, httpx.Client(timeout=300)
        self.cache_path, self.lock = cache, threading.Lock()
        self.cache: dict[str, str] = json.loads(cache.read_text()) if cache and cache.exists() else {}

    def __call__(self, question: str) -> str:
        if question in self.cache:
            return self.cache[question]
        r = self.http.post(self.url + "/v1/chat/completions", json={
            "messages": [{"role": "user", "content": PROMPT.format(q=question)}], "max_tokens": 80, "temperature": 0.1,
            "chat_template_kwargs": {"enable_thinking": False}})
        r.raise_for_status()
        text = " ".join(r.json()["choices"][0]["message"].get("content", "").split())[:300]
        with self.lock:
            self.cache[question] = text
            if self.cache_path:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                self.cache_path.write_text(json.dumps(self.cache, indent=0))
        return text
