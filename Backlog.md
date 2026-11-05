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
2. [ ] **Corpus senza documentazione Azure DevOps** (`azure-devops-docs`: AzureCLI@2, service connection, agent pool). `grep AzureCLI@2` = 0. Rivalutare l'esclusione "Azure DevOps+Terraform" della memoria.
3. [~] **Link sbagliati negli snippet di kubernetes-docs**: i link relativi Hugo diventano `https://learn.microsoft.com/docs/...` invece di `https://kubernetes.io/docs/...`. Correggere nel convertitore / risoluzione link per repo; controllare anche azurerm-docs e aks-release-notes.
   - FATTO nel codice (2026-11-05): `normalize(..., site)` e `Pipeline._site()` risolvono i link `/...` contro l'origine di `url_base` del repo; test in `tests/test_normalize.py`. Per Learn nulla cambia.
   - RESTA: l'indice attuale contiene ancora i link vecchi. Serve reprocess di kubernetes-docs (e verifica su azurerm-docs / aks-release-notes) con `docsearch update`, non fatto per non innescare un rebuild; il nightly non rielabora le pagine se il file non cambia. Modifiche non committate.
4. [ ] **Pagine vecchie in testa**: `upgrade-node-pools` (2023, regola "2 minor" obsoleta), release notes 2024 su query LTS. Usare `ms_date`/`last_commit` come segnale di freschezza o avvisare. Non penalizzare pagine con `ms_date` null.
5. [ ] **`service: null` su molte pagine AKS** (azure-aks-docs): il filtro `service=azure-kubernetes-service` le esclude. Dedurre il service dal repo di origine quando manca nel frontmatter.
6. [ ] **Rumore per parole in comune** (Container Apps, AKS bare metal, VM Insights/Azure Migrate su "az upgrade" / "Log Analytics agent"). In parte limite del corpus (nessuna pagina AKS sul ritiro di omsagent), in parte ranking.
7. [ ] **`read_doc` senza `section` su pagine lunghe** restituisce solo l'inizio senza dirlo chiaramente: indicare "chunk k/N, resto omesso" e offrire l'indice delle sezioni.
8. [ ] **Contraddizioni tra fonti** (skip dei minor "uno alla volta" vs FAQ; "2 minor" vs N-3): segnalare il conflitto e quale fonte è più recente.
9. [ ] **Buchi di corpus**: upgrade di cluster Stopped avviato dall'utente; annotazioni LB interno con Gateway API di app-routing.
10. [x] **Canarie dalle query dell'archivio** (005, 006, 010, 012, 023, 026) in `canaries.toml` (`[[query]]`, supporto in `canary.py`; 9 voci, 2026-11-05). Verificato sull'indice attuale: 8 passano, `aks-nginx-retirement` è `known_gap` (causa: punto 5, `service: null`). Limite: il canarino non usa il reranker, quindi `aks-pipelines-private` passa e NON vede il sintomo del punto 1. Non coperte (nessuna pagina attesa, buchi di corpus): 012, 023, 026.
11. [ ] Query 010 (provider azurerm 3.x->4.x, `kubernetes_version` drift) non rieseguita: verificare se la guida di upgrade 4.0 è indicizzata (azurerm-docs).

## Note
- I JSON dell'archivio sono ricostruiti a mano (snippet abbreviati): usarli solo come elenco di query, non come benchmark.
- Archivio estratto in `/tmp/claude-1000/-mnt-D500G-space-Microsoft-LLM-docsearch/954f3214-e8d8-46c9-8ebd-89e8d061a986/scratchpad/aks/` (temporaneo).
