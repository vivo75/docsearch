"""Embedding client for a local llama-server (design 6.3). Vectors are L2-normalized by the server."""
from __future__ import annotations

import shutil
import subprocess
import time
from array import array
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

BUNDLED_NOMIC = Path(
    "~/.lmstudio/.internal/bundled-models/nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf"
).expanduser()
MODEL_ID = "nomic-embed-text-v1.5.Q4_K_M"
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
MAX_CHARS = 5500           # per-slot context is 2048 tokens; stay well under for code-dense text


class EmbedServer:
    """Starts `llama-server --embedding` unless one already answers on the port."""

    def __init__(self, model: Path = BUNDLED_NOMIC, device: str = "Vulkan0", port: int = 8099,
                 ctx: int = 16384, parallel: int = 8):
        self.model, self.device, self.port, self.ctx, self.parallel = model, device, port, ctx, parallel
        self.url = f"http://127.0.0.1:{port}"
        self.proc: subprocess.Popen | None = None

    def _cmd(self, exe: str) -> list[str]:
        return [exe, "-m", str(self.model), "--embedding", "--pooling", "mean", "--device", self.device,
                "-ngl", "99", "-c", str(self.ctx), "-b", "8192", "-ub", "8192", "-np", str(self.parallel),
                "--port", str(self.port), "--host", "127.0.0.1"]

    def _up(self) -> bool:
        try:
            return httpx.get(self.url + "/health", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def __enter__(self) -> "EmbedServer":
        if self._up():
            return self
        exe = shutil.which("llama-server")
        if not exe:
            raise RuntimeError("llama-server not found on PATH")
        self.proc = subprocess.Popen(self._cmd(exe), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(240):
            if self.proc.poll() is not None:
                raise RuntimeError("llama-server exited during startup")
            if self._up():
                return self
            time.sleep(0.5)
        raise RuntimeError("llama-server did not become healthy")

    def restart(self) -> None:
        """A long-lived llama-server slows markedly under sustained load; a fresh process restores speed."""
        self.__exit__()
        self.proc = None
        self.__enter__()

    def __exit__(self, *exc) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Embedder:
    def __init__(self, url: str, workers: int = 2, batch_tokens: int = 24000, batch_items: int = 48):
        self.url, self.workers = url, workers
        self.batch_tokens, self.batch_items = batch_tokens, batch_items
        self.http = httpx.Client(timeout=600)
        self.truncated = 0

    def tokenize_len(self, text: str) -> int:
        return len(self.http.post(self.url + "/tokenize", json={"content": text}).json()["tokens"])

    def _post(self, texts: list[str]) -> list[list[float]]:
        r = self.http.post(self.url + "/v1/embeddings", json={"input": texts, "model": "x"})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]

    def _embed_batch(self, texts: list[str]) -> list[bytes]:
        try:
            vecs = self._post(texts)
        except httpx.HTTPStatusError:
            # one oversize input poisons a batch: retry singly, halving text until it fits
            vecs = []
            for t in texts:
                while True:
                    try:
                        vecs.append(self._post([t])[0])
                        break
                    except httpx.HTTPStatusError:
                        if len(t) < 200:
                            raise
                        t = t[: len(t) // 2]
                        self.truncated += 1
        return [array("f", v).tobytes() for v in vecs]

    def embed(self, texts: list[str], prefix: str = DOC_PREFIX, est_tokens: list[int] | None = None) -> list[bytes]:
        """Embed `texts` (order preserved). Length-sorted, token-budgeted batches across a few workers."""
        texts = [prefix + (t if len(t) <= MAX_CHARS else t[:MAX_CHARS]) for t in texts]
        self.truncated += sum(1 for t in texts if len(t) > MAX_CHARS + len(prefix))
        est = est_tokens or [len(t) // 3 for t in texts]
        order = sorted(range(len(texts)), key=lambda i: est[i])
        batches, cur, n = [], [], 0
        for i in order:
            if cur and (n + est[i] > self.batch_tokens or len(cur) >= self.batch_items):
                batches.append(cur); cur, n = [], 0
            cur.append(i); n += est[i]
        if cur:
            batches.append(cur)
        out: list[bytes | None] = [None] * len(texts)
        with ThreadPoolExecutor(self.workers) as ex:
            for b, res in zip(batches, ex.map(lambda b: self._embed_batch([texts[i] for i in b]), batches)):
                for i, v in zip(b, res):
                    out[i] = v
        return out  # type: ignore[return-value]
