# Backlog docsearch

Stato: `[ ]` da fare, `[~]` in corso, `[x]` fatto.

## Da fare
1. [ ] **Controllare `data/nightly.log` dopo il nightly del 2026-11-06 03:37** (primo con il crawl `azure-devops-docs`, i `service` riempiti da docfx.json e le nuove canarie). Verificare:
   - righe `convert` senza "failed"; `coverage ok` anche per il crawl `devops` (1/7 delle pagine al giorno);
   - `"problems": []` e `"status": "published"`;
   - canarie: nessun fallimento; righe `canary known-gap` (ora nessuna voce con `known_gap`);
   - nessun reprocess completo inatteso di `azure-docs` / `azure-aks-docs` (la `migrate` ha riempito i `service` fuori dal flusso git);
   - i `service` riempiti restano tali dopo l'update (`azure-aks-docs` senza `service`: circa 4 pagine);
   - `kubernetes-docs` / `azurerm-docs` senza link `learn.microsoft.com/docs/`;
   - riavvio di `docsearch-mcp` dopo il cambio di `repos.toml`.
