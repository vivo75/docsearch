"""Embedding client for a local llama-server (design 6.3). Vectors are L2-normalized by the server."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from array import array
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

HF = Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME", "~/.cache/huggingface")) / "hub").expanduser()


def hf_file(repo: str, filename: str) -> Path:
    """Path of `filename` from HF repo `repo` in the local HF cache (`hf download <repo> <filename>`).
    Returns the would-be path even if missing, so llama-server reports a clear error."""
    hits = sorted((HF / ("models--" + repo.replace("/", "--"))).glob(f"snapshots/*/{filename}"))
    return hits[-1] if hits else HF / ("models--" + repo.replace("/", "--")) / "snapshots" / "MISSING" / filename


NOMIC = hf_file("nomic-ai/nomic-embed-text-v1.5-GGUF", "nomic-embed-text-v1.5.Q4_K_M.gguf")
MODEL_ID = "nomic-embed-text-v1.5.Q4_K_M"
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
MAX_CHARS = 5500           # per-slot context is 2048 tokens; stay well under for code-dense text


class EmbedServer:
    """Starts `llama-server --embedding` unless one already answers on the port."""

    def __init__(self, model: Path = NOMIC, device: str = "Vulkan0", port: int = 8099,
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


BGE_M3 = hf_file("ggml-org/bge-m3-Q8_0-GGUF", "bge-m3-q8_0.gguf")


class BgeServer(EmbedServer):
    """bge-m3 Q8 server for the embedding experiments: CLS pooling, no prefixes, port 8095, device from BGE_DEVICE
    (default ROCm0: on the RX 7900 XTX it matches the RX 6600 slice vectors best, cos .9998, and is fastest).
    Refuses to start when something already answers on the port (EmbedServer would silently reuse an unknown server)."""
    PORT = 8095

    def __init__(self, ctx: int = 4096, parallel: int = 2):
        super().__init__(BGE_M3, os.environ.get("BGE_DEVICE", "ROCm0"), self.PORT, ctx=ctx, parallel=parallel)

    def _cmd(self, exe: str) -> list[str]:
        c = super()._cmd(exe)
        c[c.index("--pooling") + 1] = "cls"; c[c.index("-b") + 1] = "4096"; c[c.index("-ub") + 1] = "4096"
        return c

    def __enter__(self) -> "BgeServer":
        if self._up():
            raise RuntimeError(f"port {self.PORT} already answers: refusing to reuse an unknown server")
        return super().__enter__()
