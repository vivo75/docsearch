# Estrattore deterministico per il provider Terraform azurerm — valutazione e progetto

Data: 2026-11-05. Stato: prototipo in corso (vedi "Prototipo" in fondo).

## Richiesta
Un tool dell'MCP che, dato un oggetto del provider `hashicorp/terraform-provider-azurerm` (es. `azurerm_mysql_flexible_server`),
legga il codice del provider e restituisca:

1. un JSON con tutti i tipi e i valori possibili delle variabili (argomenti) dell'oggetto;
2. un diagramma di flusso del codice;
3. le API di Azure che il codice richiama.

## Risposta: è fattibile, come estrattore deterministico
Si analizza il codice Go senza usare un modello a ogni chiamata. Ho guardato un file reale
(`internal/services/mysql/mysql_flexible_server_resource.go`, 1.136 righe): è regolare. Il provider ha 693 risorse
(`*_resource.go`) e 231 data source (`*_data_source.go`) in circa 5.500 file Go non di test.

### Perché è fattibile
- **Schema e valori ammessi sono dichiarativi.** Ogni argomento è una struttura Go con `Required`/`Optional`/`Computed`,
  `ForceNew`, `Default`, `ConflictsWith`, `ValidateFunc`. Nel file di esempio: `validation.StringInSlice([]string{...})`,
  `validation.IntBetween(1, 35)`, `Default: 7`. Un parser li legge in modo esatto.
- **Le chiamate alle API sono risalibili.** Create/Read/Update/Delete usano un client dell'SDK (`client.CreateCallbackThenPoll`,
  `client.Get`, …). Dal client si arriva al file dell'SDK (`hashicorp/go-azure-sdk`), che dichiara metodo HTTP, percorso REST e
  versione API (es. `2023-12-30`).
- **Gli strumenti esistono.** `tree-sitter` è già installato; Go non c'è. Il modulo Python `tree-sitter` + `tree-sitter-go` va aggiunto al venv.

### Cosa darebbe il tool
Un JSON per risorsa con:
- argomenti, tipi, obbligatorietà, default, vincoli reciproci (ConflictsWith, ExactlyOneOf, RequiredWith, AtLeastOneOf), blocchi annidati;
- enum quando sono letterali nel codice o risolvibili nell'SDK;
- elenco ordinato delle chiamate API (operazione, metodo e percorso HTTP, versione);
- un diagramma Mermaid delle funzioni Create/Read/Update/Delete, con rami e funzioni di supporto.

### Limiti
- **Enum esterni**: `servers.PossibleValuesForCreateMode()` sta in `hashicorp/go-azure-sdk`. Si risolve scaricando solo il
  `constants.go` del pacchetto alla versione fissata in `go.mod` (raw GitHub), oppure con le specifiche REST già indicizzate.
- **Validatori personalizzati** (`validate.FlexibleServerName`): si riportano per nome ed estratto del codice; non sempre si traducono in una regola semplice.
- **"Tutti i valori possibili" = quelli che il provider accetta**, non necessariamente quelli di Azure. Valori calcolati a runtime non si enumerano.
- **Il flusso è meno preciso dello schema**: un diagramma delle chiamate in ordine con rami `if`/cicli è realistico; un grafo di controllo completo no.
- **Versione**: il codice su `main` può differire dal provider fissato dall'utente; servirebbe un parametro `ref`/tag.

## Costo
- Esecuzione: nessun costo (solo parsing, millisecondi per risorsa; nessun LLM).
- Sviluppo: prototipo su 10 risorse ≈ mezza giornata; copertura larga ≈ 2–3 sessioni (le risorse con funzioni di schema condivise o generate sono il lavoro lungo).
- Spazio: clone sparse di `internal/services` (poche centinaia di MB) + file dell'SDK scaricati a richiesta.

## Validazione senza giudizi umani
La documentazione già indicizzata dichiara gli stessi valori ("possible values are …"). Si confrontano automaticamente enum e
obbligatorietà estratti dal codice con quelli della pagina `azurerm-docs/resources/<nome>.md`.

## Alternativa più economica
Un tool che restituisce il sorgente Go di una risorsa (sola lettura) e lascia l'analisi all'agente chiamante: sviluppo quasi nullo,
ma ~14.000 token per risposta e risultati meno ripetibili. Può essere un primo passo.

## Raccomandazione
Estrattore deterministico, con prototipo su 10 risorse e validazione contro la documentazione prima di esporlo come tool MCP.

## Prototipo
- Estrattore: `src/docsearch/azurerm_extract.py` (tree-sitter-go, nessun LLM). Entry point: `extract(name, kind="resource")`.
- Validazione: `eval/azurerm_validate.py` confronta ciò che l'estrattore legge dal codice con la pagina della stessa risorsa in `azurerm-docs`. Risultati: `eval/results/azurerm-validate.json`.
- Sorgenti: `terraform-provider-azurerm` (sparse, `internal/services/*`), enum e operazioni REST da `go-azure-sdk` alla versione in `go.mod`, scaricati una volta in `data/azurerm-cache/`.

### Esito (2026-11-05, dopo i miglioramenti)
Validazione contro la documentazione su 12 risorse (`eval/azurerm_validate.py`):
- argomenti documentati trovati nel codice: **876 su 893** (98%);
- required/optional concordi: 870 su 876;
- enum documentati 141, estratti 102, concordi 101;
- chiamate API risolte su tutte le 12 risorse.

Copertura su un campione casuale di 60 risorse: **60/60 estratte senza errori**, API risolte per 49 (82%). Per le altre 11 il risultato dichiara in `unresolved`
che nessuna chiamata Azure è stata trovata staticamente (il codice delega a funzioni condivise o a un client non seguito), così chi legge non conclude che l'API non esiste.

Miglioramenti fatti rispetto al primo prototipo:
- nessun corpo di funzione copiato nel risultato: solo firma, riferimento file:riga, numero di righe e regex dei validatori personalizzati;
- blocco `provenance` in ogni risultato (repository, revisioni, licenza MPL-2.0 rilevata dai file LICENSE);
- layout nuovo del provider (`<servizio>/resources/<nome>/resource.go`), data source, qualsiasi alias del pacchetto di schema;
- helper di schema condivisi (anche tra pacchetti), mappe costruite per assegnazione o con `maps.Copy`, funzioni letterali;
- elenchi di valori definiti in variabili o funzioni (anche concatenati con `append`) e costanti locali;
- helper `commonschema` noti (zone, edge zone, identità, ResourceID);
- chiamate API seguite anche nelle funzioni di supporto del pacchetto e di altri pacchetti del provider.

### Il tool MCP
`azurerm_object(name, kind="resource"|"data_source", section="summary"|"arguments"|"api"|"flow", operation, argument)`:
- `summary`: argomenti obbligatori, ForceNew, blocchi, chiamate API, `unresolved`;
- `arguments`: elenco compatto; con `argument="blocco.figlio"` il dettaglio completo di uno solo (tipo, default, valori ammessi, conflitti);
- `api`: operazioni REST (metodo HTTP, percorso, versione API, long-running), anche per operazione;
- `flow`: diagramma Mermaid di create/read/update/delete.

Dipendenze: `tree-sitter` e `tree-sitter-go` (in `pyproject.toml`). Sorgenti: clone sparse di `terraform-provider-azurerm` con `website/docs`, `internal/services` e `go.mod`
(variabile `DOCSEARCH_AZURERM_SRC` per un altro percorso); i file dell'SDK si scaricano alla prima richiesta in `data/azurerm-cache/`. Il nightly aggiorna lo stesso clone.

### Limiti residui
- 11 risorse su 60 senza chiamata API risolta (dichiarato nel risultato).
- Gli enum calcolati a runtime (per esempio elenchi di SKU costruiti da cicli) non si enumerano.
- I validatori personalizzati sono riportati per nome e posizione, non spiegati.
- Il diagramma è un'approssimazione: sequenza di chiamate e rami `if`/cicli, non un grafo di controllo completo.
