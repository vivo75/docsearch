"""Query embedder for the legacy nomic-embed-text-v1.5 indexes (768-d) used by old experiments; production is Qwen3 (embed.prod_*)."""
import atexit
from docsearch.embed import NOMIC, NOMIC_QUERY_PREFIX, Embedder, EmbedServer


class NomicQueries:
    def __init__(self, port: int = 8104, device: str = "Vulkan0"):
        self.srv = EmbedServer(NOMIC, device, port, ctx=4096, parallel=2); self.emb = None

    def __call__(self, q: str) -> bytes:
        if self.emb is None:
            self.srv.__enter__(); atexit.register(self.srv.__exit__); self.emb = Embedder(self.srv.url, workers=1)
        return self.emb.embed([q], NOMIC_QUERY_PREFIX)[0]
