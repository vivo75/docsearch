"""Cross-encoder reranking through a local llama-server (`--reranking`)."""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

import httpx

from .embed import EmbedServer

HF = Path("~/.cache/huggingface/hub").expanduser()
MODELS = {   # name -> glob under the HF cache
    "bge-v2-m3-q8": "models--gpustack--bge-reranker-v2-m3-GGUF/snapshots/*/bge-reranker-v2-m3-Q8_0.gguf",
    "bge-v2-m3-q4": "models--sabafallah--bge-reranker-v2-m3-Q4_K_M-GGUF/snapshots/*/*.gguf",
    "qwen3-4b-q4": "models--Voodisss--Qwen3-Reranker-4B-GGUF-llama_cpp/snapshots/*/*.gguf",
}


def model_path(name: str) -> Path:
    hits = sorted(HF.glob(MODELS[name]))
    if not hits:
        raise FileNotFoundError(f"reranker {name} not found under {HF}")
    return hits[0]


class RerankServer(EmbedServer):
    def __init__(self, name: str = "bge-v2-m3-q8", device: str = "Vulkan0", port: int = 8097, parallel: int = 4):
        super().__init__(model_path(name), device, port, ctx=16384, parallel=parallel)

    def _cmd(self, exe: str) -> list[str]:
        return [exe, "-m", str(self.model), "--reranking", "--device", self.device, "-ngl", "99", "-c", str(self.ctx),
                "-b", "4096", "-ub", "4096", "-np", str(self.parallel), "--port", str(self.port), "--host", "127.0.0.1"]


class Reranker:
    """score(query, docs) -> one relevance score per doc (higher = more relevant). Optional on-disk score cache."""

    def __init__(self, url: str, name: str, max_chars: int = 1200, cache: Path | None = None):
        self.url, self.name, self.max_chars = url, name, max_chars
        self.http = httpx.Client(timeout=600)
        self.cache_path, self._lock = cache, threading.Lock()
        self.cache: dict[str, float] = {}
        if cache and cache.exists():
            self.cache = {k: v for k, v in (json.loads(l) for l in cache.read_text().splitlines() if l)}

    def _key(self, query: str, doc: str) -> str:
        return hashlib.sha1(f"{self.name}\0{query}\0{doc}".encode()).hexdigest()

    def score(self, query: str, docs: list[str]) -> list[float]:
        docs = [d[: self.max_chars] for d in docs]
        keys = [self._key(query, d) for d in docs]
        todo = [i for i, k in enumerate(keys) if k not in self.cache]
        if todo:
            r = self.http.post(self.url + "/v1/rerank", json={"query": query, "documents": [docs[i] for i in todo]})
            r.raise_for_status()
            with self._lock:
                new = {}
                for x in r.json()["results"]:
                    new[keys[todo[x["index"]]]] = float(x["relevance_score"])
                self.cache.update(new)
                if self.cache_path:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.cache_path, "a") as f:
                        f.writelines(json.dumps([k, v]) + "\n" for k, v in new.items())
        return [self.cache[k] for k in keys]
