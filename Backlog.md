# Backlog docsearch

Origine: revisione dell'archivio `AKS-upgrade-docsearch.tar` (progetto di upgrade AKS, 2026-11-05), con le query rieseguite sul server attuale.
Stato: `[ ]` da fare, `[~]` in corso, `[x]` fatto.

## Già risolti (verificato 2026-11-05)
- [x] Pagina di migrazione nginx->Gateway API ora tra i primi hit (archivio, query 005).
- [x] Guida upstream alle API rimosse (kubernetes.io deprecation-guide) indicizzata.
- [x] Risposte salvate su disco (`data/results.jsonl`).
- [x] Revisione provider azurerm: riportata in `provenance` di `azurerm_object`.

## Da fare
1. [ ] **Reranker: hit fuori finestra senza `relevance`.** Hit con `score` negativo (~-0.97) e `relevance` null (oltre `rerank_top=10`, `search.py` `_rerank`: la coda prende `floor = min-1`) finiscono in coda anche se sono pertinenti (es. `aks-firewall` sezione "Azure DevOps self-hosted agent", `app-routing-gateway-api`).
   - NON alzare `rerank_top` alla cieca: `eval/rerank-bge.log` (qset2) mostra top20/top30 non migliori di top10 (MRR .749/.758 vs .738, R@5 invariato, AUC domande senza risposta .564 -> .462 a top30).
   - Opzioni da valutare con il gate (`eval/compare.py`): (a) rerankare solo la coda con `rerank_top` più alto ma solo per le query con `confidence` bassa; (b) lasciare il tail nell'ordine fuso ma NON mostrarlo come "score -0.97" e marcare `relevance: null` esplicitamente "non rerankato"; (c) solo il caso 006 come canaria (voce 10) per misurare.
2. [~] **Corpus senza documentazione Azure DevOps** (`azure-devops-docs`: AzureCLI@2, service connection, agent pool). `grep AzureCLI@2` = 0. Rivalutare l'esclusione "Azure DevOps+Terraform" della memoria.
   - FATTO nel codice (2026-11-05): `eval/crawl_learn.py --service devops` ricostruisce `../azure-devops-docs` dalle pagine Learn (la sorgente GitHub non è leggibile senza credenziali): pipelines (222), yaml-schema (75), tasks/reference (272) = 566 pagine, copertura ok; voce `azure-devops-docs` in `repos.toml`. Il nightly (`--service all --shard auto`) lo aggiorna 1/7 al giorno.
   - RESTA: verificare l'indicizzazione (`docsearch update --canary` lanciato 20:2x, risultato da controllare) e che `grep AzureCLI@2` e la query 006 trovino agent Linux / service connection.
3. [~] **Link sbagliati negli snippet di kubernetes-docs**: i link relativi Hugo diventano `https://learn.microsoft.com/docs/...` invece di `https://kubernetes.io/docs/...`. Correggere nel convertitore / risoluzione link per repo; controllare anche azurerm-docs e aks-release-notes.
   - FATTO nel codice (2026-11-05): `normalize(..., site)` e `Pipeline._site()` risolvono i link `/...` contro l'origine di `url_base` del repo; test in `tests/test_normalize.py`. Per Learn nulla cambia.
   - RESTA: l'indice attuale contiene ancora i link vecchi. Serve reprocess di kubernetes-docs (e verifica su azurerm-docs / aks-release-notes) con `docsearch update`, non fatto per non innescare un rebuild; il nightly non rielabora le pagine se il file non cambia. Modifiche non committate.
4. [x] **Pagine vecchie in testa**: `upgrade-node-pools` (2023, regola "2 minor" obsoleta), release notes 2024 su query LTS. Usare `ms_date`/`last_commit` come segnale di freschezza o avvisare. Non penalizzare pagine con `ms_date` null.
   - FATTO come avviso, NON come penalità (2026-11-05): `search.stale_warnings()` aggiunge a `warnings` una riga se una delle prime 3 pagine ha `ms_date` ≥24 mesi più vecchio di un'altra pagina restituita dello stesso `service` (release notes escluse). Sul caso reale: `upgrade-node-pools` (2023-07) vs `supported-kubernetes-versions` (2026-09) -> avviso. Motivo della scelta: una penalità cambierebbe il ranking e richiederebbe il gate di eval (le pagine con ms_date vecchio ma ancora corrette, es. riferimenti, sarebbero penalizzate); `last_commit` non aiuta (la pagina obsoleta ha commit del 2026-10). Attivo sul server dopo il riavvio di `docsearch-mcp` (il nightly lo riavvia solo se cambia `repos.toml`).
   - Opzione futura: misurare con `eval/compare.py` una penalità lieve sul `ms_date` e adottarla solo se il gate passa.
5. [x] **`service: null` su molte pagine AKS** (azure-aks-docs): il filtro `service=azure-kubernetes-service` le esclude. Dedurre il service dal repo di origine quando manca nel frontmatter.
   - FATTO (2026-11-05): Learn lo assegna da `docfx.json` `build.fileMetadata` (`ms.service`, `ms.subservice`); nuovo `src/docsearch/docfxmeta.py` usato da `pipeline.py` (pagine nuove) e da `docsearch migrate` (backfill). Indice migrato: 6315 documenti riempiti (azure-aks-docs 442 -> 4 senza service, azure-monitor-docs, azure-docs ecc.), pubblicato `index-20261105-194056294.db`. Canaria `aks-nginx-retirement` ora passa; verificato sul server live con `service=azure-kubernetes-service`.
   - Residuo: repo senza docfx.json (architecture-center, azure-dev-docs, azure-docs-powershell, azure-pipelines-tasks, sre-agent, mcp: 0 servizi) restano senza `service`; i valori vengono dai file `docfx.json` annidati o non esistono. Da valutare un mapping per repo in `repos.toml`.
6. [ ] **Rumore per parole in comune** (Container Apps, AKS bare metal, VM Insights/Azure Migrate su "az upgrade" / "Log Analytics agent"). In parte limite del corpus (nessuna pagina AKS sul ritiro di omsagent), in parte ranking.
7. [ ] **`read_doc` senza `section` su pagine lunghe** restituisce solo l'inizio senza dirlo chiaramente: indicare "chunk k/N, resto omesso" e offrire l'indice delle sezioni.
8. [ ] **Contraddizioni tra fonti** (skip dei minor "uno alla volta" vs FAQ; "2 minor" vs N-3): segnalare il conflitto e quale fonte è più recente.
9. [ ] **Buchi di corpus**: upgrade di cluster Stopped avviato dall'utente; annotazioni LB interno con Gateway API di app-routing.
10. [x] **Canarie dalle query dell'archivio** (005, 006, 010, 012, 023, 026) in `canaries.toml` (`[[query]]`, supporto in `canary.py`; 9 voci, 2026-11-05). Verificato sull'indice attuale: 8 passano, `aks-nginx-retirement` è `known_gap` (causa: punto 5, `service: null`). Limite: il canarino non usa il reranker, quindi `aks-pipelines-private` passa e NON vede il sintomo del punto 1. Non coperte (nessuna pagina attesa, buchi di corpus): 012, 023, 026.
11. [ ] Query 010 (provider azurerm 3.x->4.x, `kubernetes_version` drift) non rieseguita: verificare se la guida di upgrade 4.0 è indicizzata (azurerm-docs).

## Note
- I JSON dell'archivio sono ricostruiti a mano (snippet abbreviati): usarli solo come elenco di query, non come benchmark.
- Archivio estratto in `/tmp/claude-1000/-mnt-D500G-space-Microsoft-LLM-docsearch/954f3214-e8d8-46c9-8ebd-89e8d061a986/scratchpad/aks/` (temporaneo).
