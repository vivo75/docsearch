"""Cross-encoder reranking through a local llama-server (`--reranking`)."""
from __future__ import annotations

import hashlib
import json
import math
import threading
from pathlib import Path

import httpx

from .embed import HF, EmbedServer

MODELS = {   # name -> glob under the HF cache
    "bge-v2-m3-q8": "models--gpustack--bge-reranker-v2-m3-GGUF/snapshots/*/bge-reranker-v2-m3-Q8_0.gguf",
    "bge-v2-m3-q4": "models--sabafallah--bge-reranker-v2-m3-Q4_K_M-GGUF/snapshots/*/*.gguf",
    "qwen3-8b-q8": "models--ethicalabs--Qwen3-Reranker-8B-GGUF/snapshots/*/Qwen3-Reranker-8B.Q8_0.gguf",
    "qwen3-4b-q4": "models--Voodisss--Qwen3-Reranker-4B-GGUF-llama_cpp/snapshots/*/*.gguf",
}


LOCAL = Path(__file__).resolve().parents[2] / "data" / "models"
LOCAL_MODELS = {"prism-4b-q8": LOCAL / "prism4b" / "prism4b-Q8_0.gguf"}   # converted here: no public GGUF exists


def model_path(name: str) -> Path:
    if name in LOCAL_MODELS:
        return LOCAL_MODELS[name]
    hits = sorted(HF.glob(MODELS[name]))
    if not hits:
        raise FileNotFoundError(f"reranker {name} not found under {HF}")
    return hits[0]


class RerankServer(EmbedServer):
    def __init__(self, name: str = "bge-v2-m3-q8", device: str = "Vulkan0", port: int = 8097, parallel: int = 4):
        self.generative = name.startswith("prism")           # scored from yes/no logits, not /v1/rerank
        super().__init__(model_path(name), device, port, ctx=16384, parallel=parallel)

    def _cmd(self, exe: str) -> list[str]:
        if self.generative:
            return [exe, "-m", str(self.model), "--device", self.device, "-ngl", "99", "-c", str(self.ctx),
                    "-np", str(self.parallel), "--port", str(self.port), "--host", "127.0.0.1"]
        return [exe, "-m", str(self.model), "--reranking", "--device", self.device, "-ngl", "99", "-c", str(self.ctx),
                "-b", "4096", "-ub", "4096", "-np", str(self.parallel), "--port", str(self.port), "--host", "127.0.0.1"]


PRISM_SYSTEM = "Judge whether the Document meets the requirements based on the Query and the Instruct provided. "
PRISM_INSTRUCT = (   # the model was trained with this one fixed prompt (infgrad/Prism-Qwen3.5-Reranker chat_template)
    'Judge if the document is relevant to the query. Reply "yes" or "no".\nOn "yes", also emit:\n'
    "<contribution>One sentence covering every core point the document contributes to the query, without elaboration.</contribution>\n"
    "<evidence>Self-contained rewrite of the query-relevant content. Rules:\n- Faithful: rephrase only; add or infer nothing.\n"
    "- Self-contained: evidence alone must fully answer the query.\n- Concise: drop query-irrelevant background.\n"
    "- Verbatim (no translation): proper nouns, terms, abbreviations, numbers, dates, code, URLs.\n"
    "- Output language: multilingual doc \u2192 query's language; else doc's language.</evidence>")
PRISM_YES, PRISM_NO = 9405, 2083          # token ids from 1_LogitScore/config.json


def prism_prompt(query: str, doc: str) -> str:
    return (f"<|im_start|>system\n{PRISM_SYSTEM}<|im_end|>\n<|im_start|>user\n<Instruct>: {PRISM_INSTRUCT}\n"
            f"<Query>: {query}\n<Document>: {doc}<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n")


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

    def _prism(self, query: str, doc: str) -> float:
        """p(yes) / (p(yes) + p(no)) at the first generated token."""
        r = self.http.post(self.url + "/completion", json={"prompt": prism_prompt(query, doc), "n_predict": 1, "n_probs": 50,
                                                           "temperature": 0, "cache_prompt": True})
        r.raise_for_status()
        top = {e["id"]: e.get("logprob", e.get("prob")) for e in r.json()["completion_probabilities"][0].get("top_logprobs", [])}
        if PRISM_YES not in top or PRISM_NO not in top:
            return 0.0 if PRISM_YES not in top else 1.0
        y, n = math.exp(top[PRISM_YES]), math.exp(top[PRISM_NO])
        return y / (y + n)

    def score(self, query: str, docs: list[str]) -> list[float]:
        docs = [d[: self.max_chars] for d in docs]
        keys = [self._key(query, d) for d in docs]
        todo = [i for i, k in enumerate(keys) if k not in self.cache]
        if todo:
            new = {}
            if self.name.startswith("prism"):
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(4) as ex:
                    for i, v in zip(todo, ex.map(lambda i: self._prism(query, docs[i]), todo)):
                        new[keys[i]] = v
            else:
                r = self.http.post(self.url + "/v1/rerank", json={"query": query, "documents": [docs[i] for i in todo]})
                r.raise_for_status()
                for x in r.json()["results"]:
                    new[keys[todo[x["index"]]]] = float(x["relevance_score"])
            with self._lock:
                self.cache.update(new)
                if self.cache_path:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.cache_path, "a") as f:
                        f.writelines(json.dumps([k, v]) + "\n" for k, v in new.items())
        return [self.cache[k] for k in keys]
