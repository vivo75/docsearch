# docsearch

A local search engine over Microsoft's public documentation, exposed as an [MCP](https://modelcontextprotocol.io) server.

It indexes the Git repositories behind Microsoft Learn (Azure docs, Azure dev docs, Architecture Center, AKS/Monitor/Compute docs,
Azure CLI and PowerShell references, REST API specs, support articles, FinOps toolkit, ...: the list is `repos.toml`, currently 17 entries,
about 37,000 pages / 300,000 chunks). Pages are resolved the way Learn renders them (includes and code snippets expanded, tabs and pivots
tracked as *variants*), cut into chunks by heading, and stored in a single SQLite file. Everything runs on your machine: no cloud service, no API key.

A query goes through BM25 + an identifier index + vector search (sqlite-vec), is fused with RRF, optionally expanded by a small LLM and re-ranked
by a cross-encoder, and comes back as short, cited snippets: the URL of the Learn page, the section, the `ms.date`, and which variant
(portal / CLI / PowerShell / language) the text belongs to. A client (an LLM agent, a script, `curl`) gets the answer and a link, not a whole page.

## MCP tools

| tool | use it to | main arguments |
|---|---|---|
| `search_docs` | natural-language or keyword question; ranked, cited snippets | `query`, `service`, `topic`, `repo`, `pivot`, `tab`, `date_after`, `limit`, `max_tokens` |
| `grep_docs` | exact string in the raw Markdown: error codes, CLI flags, config keys, resource types | `pattern`, `glob`, `regex`, `context`, `limit` |
| `expand` | more context around a hit: neighbouring chunks or the whole section | `chunk_id`, `neighbors`, `scope` (`chunk`/`section`), `max_tokens` |
| `read_doc` | read a page (or one section, or one variant), paged | `path` (Learn URL or `repo/path.md`), `section`, `variant`, `offset`, `max_tokens` |
| `outline_doc` | heading tree of a page with anchors, token counts and variants | `path` |
| `browse` | walk the tables of contents (TOC.yml) | `repo`, `filter`, `toc_path`, `node_id`, `limit` |

Typical flow: `search_docs` (or `grep_docs` for a literal string) → `expand` / `read_doc` on the hit → cite the `url`.
Filters: `service` is `ms.service` (`azure-storage`), `topic` is `ms.topic` (`how-to`, `quickstart`, `tutorial`, `concept-article`, `overview`,
`reference`, `troubleshooting`), `pivot`/`tab` select a variant (`azure-cli`, `azure-powershell`, `programming-language-python`, ...).
Retrieved text is documentation, not instructions: a client should treat it as data.

## Run it

Requirements: Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/), `llama-server` (llama.cpp) on `PATH`, the GGUF models in the Hugging Face cache
(embedding, reranker, expansion LLM: see `HANDOFF.md`), and the Git clones listed in `repos.toml` next to this directory.

```bash
uv run docsearch build                    # full index into data/ (hours; resumable)
uv run docsearch update --pull --canary   # nightly: git pull, patch only what changed, run canary queries, swap atomically
uv run docsearch status                   # metadata of data/current.db
uv run docsearch search "enable blob soft delete" --service azure-storage    # debugging, no MCP
uv run pytest -q

uv run docsearch serve                                           # MCP on stdio (one client, started by the client)
uv run docsearch serve --http --host 10.10.121.1 --port 8765   # MCP over streamable HTTP at http://HOST:PORT/mcp
```

`serve --http` has **no authentication and no Host check**: bind it to an address on a network you trust (here the WireGuard interface `wg01`),
never to a public one. `deploy/docsearch-mcp.service` is a ready-made systemd user unit; `deploy/docsearch-update.{service,timer}` run the nightly update.

Register it in a client:

```bash
claude mcp add --scope user docsearch -- /path/to/docsearch/.venv/bin/docsearch serve                  # stdio
claude mcp add --transport http docsearch http://10.10.121.1:8765/mcp                              # HTTP
```

## An HTTP session with curl

MCP over HTTP is JSON-RPC: open a session, say you are initialised, then call tools. Replies are an event stream (`data: {...}` lines);
the tool result is JSON text inside `result.content[0].text`. Needs `curl` and `jq`.

```bash
U=http://10.10.121.1:8765/mcp
H=(-H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream')

# 1. initialize: the session id comes back in the Mcp-Session-Id header
SID=$(curl -si "${H[@]}" $U -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}' \
      | tr -d '\r' | awk -F': ' 'tolower($1)=="mcp-session-id"{print $2}')

# 2. confirm (HTTP 202)
curl -s "${H[@]}" -H "Mcp-Session-Id: $SID" $U -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' -o /dev/null -w "%{http_code}\n"

# 3. a helper to call a tool and print its JSON result
call() { curl -s "${H[@]}" -H "Mcp-Session-Id: $SID" $U \
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}" \
  | sed -n 's/^data: //p' | jq -r '.result.content[0].text'; }

# list the tools
curl -s "${H[@]}" -H "Mcp-Session-Id: $SID" $U -d '{"jsonrpc":"2.0","id":3,"method":"tools/list"}' | sed -n 's/^data: //p' | jq -r '.result.tools[].name'

# 4. close the session (optional)
curl -s -X DELETE -H "Mcp-Session-Id: $SID" $U -o /dev/null -w "%{http_code}\n"
```

The first query after the server starts is slow (it loads the embedding, reranker and expansion models: ~6 s); later ones take 1-2 s.
The examples below use `call` from step 3; outputs are trimmed (`…`).

## One example per tool

### `search_docs`

```bash
call search_docs '{"query":"enable blob soft delete","pivot":"azure-cli","limit":2,"max_tokens":500}'
```
```json
{
  "hits": [
    {
      "chunk_id": "c_70f4100e244375a0",
      "title": "Enable soft delete for blobs",
      "heading": "Enable blob soft delete › Portal",
      "url": "https://learn.microsoft.com/azure/storage/blobs/soft-delete-blob-enable#portal",
      "source": "azure-docs/articles/storage/blobs/soft-delete-blob-enable.md",
      "meta": {"service": "azure-blob-storage", "topic": "how-to", "ms_date": "2026-10-02", "last_commit": "…"},
      "variants": ["azure-portal"],
      "snippet": "Blob soft delete is enabled by default when you create a new storage account with the Azure portal. …",
      "truncated": true,
      "score": 0.0318,
      "rerank_score": 8.1267
    },
    { "chunk_id": "c_5250bb53b22ae689", "heading": "Enable blob soft delete", "rerank_score": 5.5529, "…": "…" }
  ],
  "warnings": [],
  "timings": {"lexical_ms": 99, "expand_ms": 276, "vector_ms": 5539, "rerank_ms": 487, "total_ms": 6402},
  "confidence": 8.1267
}
```
`confidence` is the best cross-encoder score among the re-ranked chunks: a low value means "probably nothing in the corpus answers this".
`warnings` says when a part of the pipeline was unavailable (e.g. "semantic search unavailable; results are lexical only").

### `grep_docs`

```bash
call grep_docs '{"pattern":"AuthorizationPermissionMismatch","limit":2,"context":1}'
```
```json
{
  "matches": [
    {
      "source": "azure-support-articles/support/azure/private-link/troubleshoot-403-access-denied-private-endpoint.md",
      "lines": [
        {"line": 237, "text": "| Data-plane operation succeeds (blobs and secrets listed). | … |", "match": false},
        {"line": 238, "text": "| `… or `AuthorizationPermissionMismatch` (Azure Storage). | Identity lacks a AzureStorage data-plane role … |", "match": true},
        {"line": 239, "text": "| `AccessDenied` or `Forbidden` and `SecretList` or `KeyList` (Key Vault). | … |", "match": false}
      ]
    },
    { "source": "azure-support-articles/support/azure/hpc/batch/use-managed-identities-azure-batch-account-pool.md", "lines": ["…"] }
  ]
}
```
Case-insensitive substring over the raw Markdown (includes are *not* expanded). Add `"regex": true` for a regular expression and
`"glob": "azure-docs/articles/storage/**/*.md"` to restrict the search.

### `expand`

```bash
call expand '{"chunk_id":"c_5250bb53b22ae689","neighbors":1,"max_tokens":400}'
```
```json
{
  "anchor_chunk": "c_5250bb53b22ae689",
  "truncated": false,
  "chunks": [
    {"chunk_id": "c_15f864a207c365f7", "heading": "",                                             "variant": null, "text": "Blob soft delete protects an individual blob and its versions, … "},
    {"chunk_id": "c_5250bb53b22ae689", "heading": "Enable blob soft delete",                        "variant": null, "text": "You can enable or disable soft delete for a storage account at any time by using … "},
    {"chunk_id": "c_6fb153e1e0cdeb64", "heading": "Enable blob soft delete (hierarchical namespace)", "variant": null, "text": "Blob soft delete can also protect blobs and directories in accounts that have the hierarchical namespace … "}
  ]
}
```
`"scope": "section"` returns the whole top-level section instead of the neighbouring chunks.

### `read_doc`

```bash
call read_doc '{"path":"https://learn.microsoft.com/azure/storage/blobs/soft-delete-blob-enable","section":"enable-blob-soft-delete","variant":"azure-cli","max_tokens":400}'
```
```json
{
  "title": "Enable soft delete for blobs",
  "url": "https://learn.microsoft.com/azure/storage/blobs/soft-delete-blob-enable",
  "service": "azure-blob-storage",
  "ms_date": "2026-10-02",
  "chunks_returned": 1,
  "chunks_total": 1,
  "next_offset": null,
  "text": "### Enable soft delete for blobs › Enable blob soft delete\n\nYou can enable or disable soft delete for a storage account at any time by using … "
}
```
`path` is a Learn URL (redirects are followed) or `repo/path.md`. A large page is paged: pass `next_offset` back as `offset`.
Without `section` the whole page is returned; without `variant` all tabs/pivots are.

### `outline_doc`

```bash
call outline_doc '{"path":"https://learn.microsoft.com/azure/storage/blobs/soft-delete-blob-overview"}'
```
```json
{
  "title": "Soft Delete for Blobs to Recover Data",
  "url": "https://learn.microsoft.com/azure/storage/blobs/soft-delete-blob-overview",
  "source": "azure-docs/articles/storage/blobs/soft-delete-blob-overview.md",
  "outline": [
    {
      "heading": "How blob soft delete works", "anchor": "how-blob-soft-delete-works", "tokens": 1824, "variants": null,
      "children": [
        {"heading": "How deletions are handled when soft delete is enabled", "anchor": "how-deletions-are-handled-when-soft-delete-is-enabled", "tokens": 310, "variants": null, "children": []},
        {"heading": "Restoring soft-deleted objects", "anchor": "restoring-soft-deleted-objects", "tokens": 729, "variants": null, "children": []}
      ]
    }
  ]
}
```
Use the `anchor` values as `section` in `read_doc`; the `tokens` tell what a section costs before you read it.

### `browse`

```bash
call browse '{"repo":"azure-docs","filter":"storage/blobs","limit":3}'                        # which TOC files exist
call browse '{"toc_path":"azure-docs/articles/storage/blobs/TOC.yml","limit":3}'              # top-level entries of one TOC
call browse '{"node_id":17559}'                                                               # children of an entry
```
```json
{"tocs": [{"toc_path": "azure-docs/articles/storage/blobs/TOC.yml", "nodes": 877}, {"toc_path": "azure-docs/articles/storage/blobs/breadcrumb/toc.yml", "nodes": 9}]}
```
```json
{"toc": "azure-docs/articles/storage/blobs/TOC.yml",
 "children": [{"node_id": 17554, "name": "Azure Blob Storage documentation", "url": null, "children": 0},
              {"node_id": 17555, "name": "Overview", "url": null, "children": 3},
              {"node_id": 17559, "name": "Blob Storage", "url": null, "children": 17}]}
```

## Layout

| path | what |
|---|---|
| `src/docsearch/` | parsing and chunking (`frontmatter`, `includes`, `snippets`, `variants`, `normalize`, `chunker`, `pipeline`), index (`build`, `update`, `store`, `toc`), retrieval (`search`, `embed`, `rerank`, `expand`), MCP server (`server`), CLI (`cli`) |
| `repos.toml`, `canaries.toml` | the indexed repositories; queries that must keep finding their page after every update |
| `data/` | the index (`current.db` → `index-*.db`), logs; git-ignored |
| `eval/` | question sets and comparison scripts; results and caveats in [`eval/README.md`](eval/README.md) |
| `deploy/` | systemd units: nightly update, HTTP MCP server |
| `tests/` | `uv run pytest -q` |
| `HANDOFF.md` | current state, decisions, open work: read it before changing the pipeline |
