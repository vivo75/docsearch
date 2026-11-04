# Installare docsearch

Guida per montare docsearch su una macchina nuova: software, modelli, corpus (i repository Git della documentazione), prima costruzione
dell'indice, registrazione del server MCP e aggiornamento notturno. Cos'è e come si usa: `README.md`. Stato e decisioni: `HANDOFF.md`.

> Le istruzioni derivano dalla macchina attuale (Fedora 45, RX 7900 XTX) e dai file del progetto. La procedura completa su una macchina
> vuota non è mai stata rifatta da capo dall'inizio alla fine: se un passo non torna, `HANDOFF.md` ("Porting checklist") racconta come è stato fatto l'ultimo trasloco.

## 1. Cosa serve

| risorsa | requisito | note |
|---|---|---|
| Sistema | Linux con systemd utente | testato su Fedora; i comandi `dnf` vanno adattati |
| GPU | una GPU con driver Vulkan e ≥ 8 GB di VRAM | sviluppato su RX 6600 8 GB (lenta) e RX 7900 XTX 24 GB. Embedding, reranker e modello di espansione stanno insieme in 24 GB. Senza GPU `llama-server` può girare su CPU (`DOCSEARCH_EMBED_DEVICE`), ma la costruzione dell'indice diventa molto lunga |
| RAM | 16 GB minimo, 32+ consigliati | la cache vettoriale `.npy` pesa ~3 GB e viene letta in memoria |
| Disco | ~150 GB liberi (stima) | `azure-docs` da solo ~33 GB, `azure-rest-api-specs` ~3 GB; ogni indice 4 GB + 3 GB di cache vettoriale, ne restano 3 versioni (~21 GB) |
| Software | `git`, `ripgrep` (`rg`), `uv`, `llama-server` (llama.cpp), Python ≥ 3.12 | `uv` scarica da solo un Python adatto |

## 2. Struttura delle cartelle

`repos.toml` dichiara `root = "../.."`: il corpus sono repository **fratelli** della cartella del progetto, e i percorsi sono relativi a quella radice.

```
/percorso/Microsoft/                 <- radice del corpus
├── azure-docs/  azure-dev-docs/  architecture-center/  ...   (cloni Git, vedi §5)
└── LLM/docsearch/                   <- questo progetto (repos.toml, src/, data/)
```

Se sposti il progetto, tieni la stessa distanza dalla radice oppure cambia `root` in `repos.toml`.

## 3. Strumenti di base

```bash
sudo dnf install git ripgrep                     # Debian/Ubuntu: apt install git ripgrep
curl -LsSf https://astral.sh/uv/install.sh | sh  # oppure: sudo dnf install uv
git clone <url-di-docsearch> /percorso/Microsoft/LLM/docsearch
cd /percorso/Microsoft/LLM/docsearch
uv sync                                          # crea .venv con httpx, mcp, pyyaml, sqlite-vec, numpy, pytest
uv run pytest -q                                 # ~100 test, pochi secondi, non richiedono GPU né modelli
```

I test passano anche senza modelli e senza corpus: servono per verificare l'ambiente Python.

## 4. llama.cpp (`llama-server`)

docsearch avvia da solo i processi `llama-server` che gli servono (embedding, reranker, espansione delle query); trova l'eseguibile nel `PATH`.
Costruiscilo con il backend Vulkan, **statico e senza opzioni di debug** (una build con `GGML_VULKAN_CHECK_RESULTS` o i layer di validazione è andata in segfault all'avvio):

```bash
sudo dnf install cmake gcc-c++ vulkan-headers vulkan-loader-devel glslc shaderc   # nomi dei pacchetti da adattare
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DGGML_VULKAN=ON -DBUILD_SHARED_LIBS=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build -j --target llama-server
sudo install build/bin/llama-server /usr/local/bin/
llama-server --version                           # versione usata finora: build 12101
```

Il servizio notturno usa `PATH=/usr/local/bin:/usr/bin`: installa `llama-server` in uno di questi due posti.
Se usi un altro backend (ROCm, CUDA), imposta il dispositivo con `DOCSEARCH_EMBED_DEVICE` (predefinito `Vulkan0`; vedi §9).

## 5. Modelli

Vanno nella cache di Hugging Face (`~/.cache/huggingface/hub`, oppure `HF_HUB_CACHE` / `HF_HOME`). Installa il comando `hf` e scarica:

```bash
uv tool install huggingface_hub
hf download Qwen/Qwen3-Embedding-4B-GGUF Qwen3-Embedding-4B-Q8_0.gguf                   # embedding (obbligatorio, ~4,3 GB)
hf download gpustack/bge-reranker-v2-m3-GGUF bge-reranker-v2-m3-Q8_0.gguf               # reranker (obbligatorio)
hf download lmstudio-community/gemma-4-E4B-it-GGUF gemma-4-E4B-it-Q4_K_M.gguf           # espansione delle query (consigliato)
hf download unsloth/Qwen3.8-27B-GGUF Qwen3.8-27B-UD-Q4_K_M.gguf                         # solo per i riassunti di `docsearch changes --summarize` (facoltativo)
```

- Senza il modello di embedding non si può costruire l'indice. Se il reranker manca, la ricerca prosegue con l'ordine fuso e lo segnala in `warnings`.
- Senza Gemma l'espansione delle query viene saltata (`DOCSEARCH_EXPAND=off` per spegnerla di proposito).
- I modelli per gli esperimenti in `eval/` (nomic, bge-m3, Qwen3-Reranker, Prism) non servono per l'uso normale.

## 6. Il corpus (repository Git)

L'elenco è `repos.toml` (20 voci). I cloni **superficiali** bastano: l'aggiornamento notturno confronta le versioni con `git diff` e, se il commit vecchio non esiste più, rielabora l'intero repository.

```bash
cd /percorso/Microsoft
S=--shallow-since=2026-01-01
# repository principali
git clone $S https://github.com/MicrosoftDocs/azure-docs.git
git clone $S https://github.com/MicrosoftDocs/azure-dev-docs
git clone $S https://github.com/MicrosoftDocs/architecture-center
git clone $S https://github.com/MicrosoftDocs/azure-aks-docs.git
git clone $S https://github.com/MicrosoftDocs/azure-monitor-docs.git
git clone $S https://github.com/MicrosoftDocs/azure-compute-docs.git
git clone $S https://github.com/MicrosoftDocs/azure-docs-powershell.git
git clone $S https://github.com/MicrosoftDocs/mcp.git
git clone $S https://github.com/Azure/azure-rest-api-specs
git clone $S https://github.com/Azure/azure-rest-api-specs-examples
git clone $S https://github.com/Azure/azure-cli
git clone $S https://github.com/microsoft/finops-toolkit
git clone $S https://github.com/microsoft/azure-pipelines-tasks.git
git clone $S https://github.com/microsoft/sre-agent
# Azure CLI (guide + riferimento comandi) e articoli di supporto: solo le cartelle che servono (sparse checkout)
git clone $S --filter=blob:none --sparse https://github.com/MicrosoftDocs/azure-docs-cli.git
git -C azure-docs-cli sparse-checkout set docs-ref-autogen/Latest-version docs-ref-conceptual openpublishing-redirection-config
git clone $S --filter=blob:none --sparse https://github.com/MicrosoftDocs/SupportArticles-docs.git
git -C SupportArticles-docs sparse-checkout set support/azure
```

Dopo il clone controlla `docs_root` in `repos.toml`: per PowerShell indicizza **una sola** cartella `azps-X.Y.Z` (ora `azps-16.5.0`); se nel clone ce n'è una più recente, aggiornala.

### Cosmos DB, Key Vault e MySQL (ricostruiti)

I sorgenti di questi tre servizi sono repository privati (`nosql-docs-pr`, `azure-security-docs-pr`, `azure-databases-docs-pr`). Si ricostruiscono dalle pagine renderizzate di Learn (1 richiesta ogni 0,8 s):

```bash
cd /percorso/Microsoft/LLM/docsearch
uv run python eval/crawl_learn.py --service all     # prima volta: scarica tutto (circa 600 pagine, una decina di minuti); crea ../nosql-docs, ../azure-security-docs e ../azure-databases-docs (MySQL)
```

Il nightly (§8) ne riscarica un settimo al giorno (`--shard auto`). Se non vuoi uno di questi servizi, togli la voce corrispondente (`nosql-docs`, `azure-security-docs`, `azure-databases-docs`) da `repos.toml`.

### Repository dipendenti (consigliato)

Molte pagine includono frammenti di codice e testi da altri repository elencati in `dependent_repositories` di `.openpublishing.publish.config.json` (circa 117 voci in `azure-docs`). Senza di essi molte pagine restano "non risolte" (testi e snippet mancanti) e la build rifiuta di pubblicare se superano il 15%. Clonali accanto al corpus con il nome indicato in `path_to_root`:

```bash
cd /percorso/Microsoft
for r in azure-docs azure-dev-docs; do
  python3 - "$r" <<'EOF'
import json, subprocess, sys, os
cfg = json.load(open(f"{sys.argv[1]}/.openpublishing.publish.config.json"))
for d in cfg.get("dependent_repositories", []):
    name, url = d["path_to_root"], d["url"]
    if name.startswith("_") or os.path.exists(name):   # _themes e simili non servono
        continue
    r = subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, name])
    print(name, "ok" if r.returncode == 0 else "NON CLONATO (privato?)")
EOF
done
```

Tre repository sono privati e non si possono clonare: `reusable-content`, `azure-dev-docs-pr`, `azure-policy-autogen-docs`. Qui sono sostituiti da file ricostruiti a mano dalle pagine renderizzate (cartelle `reusable-content/` e `azure-dev-docs-pr/` accanto al corpus, con `RECONSTRUCTED.md`); **non fanno parte del repository docsearch**. Senza di essi le pagine che li includono restano segnalate come non risolte; se la soglia del 15% blocca la build, `docsearch build --force` pubblica comunque.

## 7. Primo indice

```bash
cd /percorso/Microsoft/LLM/docsearch
uv run docsearch build            # analisi + chunk (parallela) + embedding (riprendibile); alcune ore, soprattutto l'embedding
uv run docsearch status           # metadati e health dell'indice (data/current.db)
uv run docsearch search "enable blob soft delete" --service azure-storage
```

- La build scrive `data/index-<timestamp>.partial`; se si interrompe, riprendi con `docsearch build --resume data/index-….partial`. Alla fine verifica la coerenza, crea la cache vettoriale `.npy` e punta `data/current.db` al nuovo indice con uno scambio atomico.
- Prova ridotta: `docsearch build --repos architecture-center --limit 200 --force`.
- Se `docsearch search` stampa `semantic search unavailable` o `reranker unavailable`, `llama-server` non parte: controlla `llama-server --version` e `ldd $(which llama-server) | grep "not found"`.
- Primo avvio a freddo di una ricerca: ~15 s (carica i modelli); poi ~1 s.

## 8. Servire e aggiornare

### Server MCP

Con Claude Code (processo avviato dal client, comunicazione su stdio):

```bash
claude mcp add --scope user docsearch -- /percorso/Microsoft/LLM/docsearch/.venv/bin/docsearch serve
```

Come servizio HTTP sulla rete (**nessuna autenticazione, nessun controllo dell'host**: usalo solo su una rete fidata, ad esempio un'interfaccia WireGuard):

```bash
# modifica deploy/docsearch-mcp.service: percorso del progetto e indirizzo --host
mkdir -p ~/.config/systemd/user && cp deploy/docsearch-mcp.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now docsearch-mcp
claude mcp add --transport http docsearch http://<indirizzo>:8765/mcp
loginctl enable-linger "$USER"      # il servizio parte anche senza sessione aperta
```

### Aggiornamento notturno

`deploy/nightly.sh` fa `git pull` dei repository, rielabora solo le pagine cambiate, esegue le query di controllo (`canaries.toml`), pubblica l'indice in modo atomico e scrive un rapporto in `data/reports/`. Se qualcosa non va, l'indice in uso resta intatto.

```bash
# controlla i percorsi in deploy/docsearch-update.service e deploy/nightly.sh
cp deploy/docsearch-update.service deploy/docsearch-update.timer ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now docsearch-update.timer
systemctl --user list-timers docsearch-update.timer      # prossima esecuzione (03:30 + fino a 10 min)
tail data/nightly.log
```

Prova a mano: `uv run docsearch update --pull --canary` (oppure `--dry-run` per vedere cosa cambierebbe).
`deploy/nightly.sh` chiama direttamente `.venv/bin/docsearch`, quindi non dipende da `uv` nel `PATH` di systemd.

## 9. Variabili d'ambiente utili

| variabile | effetto |
|---|---|
| `HF_HUB_CACHE` / `HF_HOME` | dove cercare i modelli GGUF |
| `DOCSEARCH_DB` | indice da servire (predefinito `data/current.db`) |
| `DOCSEARCH_EMBED_DEVICE`, `DOCSEARCH_EMBED_PORT` | dispositivo (`Vulkan0`) e porta del server di embedding |
| `DOCSEARCH_RERANK` | nome del reranker (`bge-v2-m3-q8`) oppure `off` |
| `DOCSEARCH_EXPAND`, `DOCSEARCH_EXPAND_IDLE`, `DOCSEARCH_EXPAND_DEVICE`, `DOCSEARCH_EXPAND_PORT` | espansione delle query (`off` la spegne; scarica Gemma dopo 300 s di inattività) |
| `DOCSEARCH_VECMAT=off` | ignora la cache vettoriale `.npy` e usa sqlite-vec (più lento, ~13×) |
| `DOCSEARCH_QUERY_LOG` | file `.jsonl` del registro delle query (`data/queries.jsonl`) |

Porte usate in locale da `llama-server`: 8102 (query), 8103 (build/update), 8104 (controlli notturni), 8097 (reranker), 8096 (espansione), 8105 (rapporti); il server MCP HTTP usa 8765.
Tutti i processi `llama-server` ascoltano solo su `127.0.0.1`.

## 10. Verifica finale

```bash
uv run pytest -q                                   # test (nessuna GPU necessaria)
uv run docsearch status                            # "health: ok"
uv run docsearch search "create an AKS node pool with azure cli" --limit 3
uv run docsearch update --dry-run                  # mostra cosa cambierebbe (le query di controllo girano solo con `update --canary` senza --dry-run)
```

Se tutto torna, l'MCP risponde con 6 strumenti: `search_docs`, `grep_docs`, `expand`, `read_doc`, `outline_doc`, `browse`.

## Problemi frequenti

| sintomo | causa probabile |
|---|---|
| `semantic search unavailable` / `reranker unavailable` | `llama-server` non parte: versione, librerie mancanti (`ldd … \| grep "not found"`), modello assente in cache, porta occupata |
| `build NOT published … unresolved include/snippet rate` | mancano i repository dipendenti (§6) o le cartelle ricostruite; `--force` per pubblicare lo stesso |
| servizio systemd termina con `status=127` | eseguibile non trovato nel `PATH` di systemd: usa percorsi assoluti (`.venv/bin/docsearch`) |
| ricerche lente (~1,5 s in più) | manca la cache `.npy`: `uv run docsearch vecmat` |
| `docsearch update` rielabora un repository intero | normale con cloni superficiali che hanno perso il vecchio commit; i vettori già calcolati si riusano per hash |
